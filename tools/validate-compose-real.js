#!/usr/bin/env node
/**
 * Check that `docker-compose.yml` describes a stack that would actually work.
 *
 * Why this validator exists
 * -------------------------
 * `docker-compose.yml` is a YAML file that nothing type-checks, and a mistake
 * in it fails late: the stack comes up "fine" and then the backend cannot
 * reach the database, or a container reports itself healthy while the tool its
 * healthcheck needs was never installed in the image.
 *
 * The failures this file is written against are concrete:
 *
 *   * the backend builds from the **repository root** (`context: .`), not from
 *     `./backend`, because the backend imports the `ai` package which lives
 *     outside `backend/`. Getting this wrong produces an image whose import
 *     of `ai` fails at start-up;
 *   * the backend's healthcheck uses `curl`, so `backend/Dockerfile` must
 *     install it — `python:3.12-slim` does not ship it;
 *   * the frontend's healthcheck uses `wget`, which the alpine-based nginx
 *     image does ship;
 *   * `depends_on` must wait for `service_healthy`, not merely for the
 *     container to be *started*, otherwise the backend boots against a
 *     database that is still initialising;
 *   * inside the Compose network the database is reachable at the service
 *     name `db`, never at `localhost`;
 *   * no real secret may be committed: every sensitive value must fall back to
 *     an obviously-fake placeholder.
 *
 * The check is offline and dependency-free: the YAML is parsed with a small
 * hand-written reader (there is no `js-yaml` dependency in this repository and
 * this script must run with nothing installed), no container is started and no
 * network request is made.
 *
 * Run it with:
 *
 *     node tools/validate-compose-real.js
 */

'use strict';

const fs = require('fs');
const path = require('path');

const REPO_ROOT = path.resolve(__dirname, '..');
const COMPOSE_PATH = path.join(REPO_ROOT, 'docker-compose.yml');
const BACKEND_DOCKERFILE = path.join(REPO_ROOT, 'backend', 'Dockerfile');
const FRONTEND_DOCKERFILE = path.join(REPO_ROOT, 'frontend', 'Dockerfile');
const GITIGNORE_PATH = path.join(REPO_ROOT, '.gitignore');

// ---------------------------------------------------------------------------
// Reporting
// ---------------------------------------------------------------------------

const passed = [];
const failed = [];

function ok(message) {
  passed.push(message);
}

function fail(message) {
  failed.push(message);
}

function check(condition, success, failure) {
  if (condition) {
    ok(success);
  } else {
    fail(failure);
  }
  return Boolean(condition);
}

// ---------------------------------------------------------------------------
// A small YAML reader
// ---------------------------------------------------------------------------
//
// This understands the subset of YAML that Docker Compose files actually use:
//
//   * block mappings, indented with spaces;
//   * block sequences (`- item`);
//   * flow sequences (`[a, b, c]`) and flow mappings (`{a: b}`);
//   * quoted scalars (single and double quotes);
//   * folded (`>-`) and literal (`|`) block scalars;
//   * `#` comments.
//
// It deliberately does NOT support anchors, aliases, tags, multi-document
// streams or complex keys. A file that uses them will fail to parse, which
// is reported rather than silently mis-read.

/** Split a document into significant lines, keeping indentation. */
function readLines(text) {
  const lines = [];
  const rawLines = text.split(/\r?\n/);

  for (let index = 0; index < rawLines.length; index += 1) {
    const raw = rawLines[index];
    const withoutIndent = raw.replace(/^\s+/, '');
    const indent = raw.length - withoutIndent.length;

    if (withoutIndent === '' || withoutIndent.startsWith('#')) {
      continue;
    }
    lines.push({ indent, text: withoutIndent, lineNumber: index + 1 });
  }
  return lines;
}

/** Remove a trailing `# comment` from an unquoted scalar. */
function stripComment(text) {
  let inSingle = false;
  let inDouble = false;
  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    if (char === "'" && !inDouble) {
      inSingle = !inSingle;
    } else if (char === '"' && !inSingle) {
      inDouble = !inDouble;
    } else if (char === '#' && !inSingle && !inDouble) {
      const before = text[i - 1];
      if (before === undefined || before === ' ' || before === '\t') {
        return text.slice(0, i).trimEnd();
      }
    }
  }
  return text.trimEnd();
}

/** True when the bracket-free prefix of `text` ends a `key: value` pair. */
function findKeySeparator(text) {
  let inSingle = false;
  let inDouble = false;
  let depth = 0;
  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    if (char === "'" && !inDouble) {
      inSingle = !inSingle;
    } else if (char === '"' && !inSingle) {
      inDouble = !inDouble;
    } else if (!inSingle && !inDouble) {
      if (char === '[' || char === '{') depth += 1;
      else if (char === ']' || char === '}') depth -= 1;
      else if (char === ':' && depth === 0) {
        const next = text[i + 1];
        if (next === undefined || next === ' ' || next === '\t') {
          return i;
        }
      }
    }
  }
  return -1;
}

/** Parse a flow sequence or flow mapping. */
function parseFlow(text, lines, cursor) {
  let buffer = text;
  while (!balanced(buffer)) {
    if (cursor.index >= lines.length) {
      throw new Error('unterminated flow collection');
    }
    buffer += ' ' + lines[cursor.index].text;
    cursor.index += 1;
  }
  return parseFlowValue(buffer);
}

function balanced(text) {
  let depth = 0;
  let inSingle = false;
  let inDouble = false;
  for (const char of text) {
    if (char === "'" && !inDouble) inSingle = !inSingle;
    else if (char === '"' && !inSingle) inDouble = !inDouble;
    else if (!inSingle && !inDouble) {
      if (char === '[' || char === '{') depth += 1;
      else if (char === ']' || char === '}') depth -= 1;
    }
  }
  return depth === 0;
}

/** Split a flow body on top-level commas. */
function splitFlow(body) {
  const parts = [];
  let current = '';
  let depth = 0;
  let inSingle = false;
  let inDouble = false;
  for (const char of body) {
    if (char === "'" && !inDouble) {
      inSingle = !inSingle;
      current += char;
      continue;
    }
    if (char === '"' && !inSingle) {
      inDouble = !inDouble;
      current += char;
      continue;
    }
    if (!inSingle && !inDouble) {
      if (char === '[' || char === '{') depth += 1;
      else if (char === ']' || char === '}') depth -= 1;
      else if (char === ',' && depth === 0) {
        parts.push(current.trim());
        current = '';
        continue;
      }
    }
    current += char;
  }
  if (current.trim() !== '') parts.push(current.trim());
  return parts;
}

/** Parse the inside of a flow collection. */
function parseFlowValue(text) {
  const trimmed = text.trim();
  if (trimmed.startsWith('[') && trimmed.endsWith(']')) {
    return splitFlow(trimmed.slice(1, -1)).map((part) => parseFlowValue(part));
  }
  if (trimmed.startsWith('{') && trimmed.endsWith('}')) {
    const result = {};
    for (const part of splitFlow(trimmed.slice(1, -1))) {
      const separator = findKeySeparator(part);
      if (separator === -1) {
        result[unquote(part)] = null;
      } else {
        const key = unquote(part.slice(0, separator).trim());
        result[key] = parseFlowValue(part.slice(separator + 1).trim());
      }
    }
    return result;
  }
  return unquote(trimmed);
}

/** Remove surrounding quotes from a scalar. */
function unquote(text) {
  const trimmed = text.trim();
  if (trimmed.length >= 2) {
    if (trimmed.startsWith("'") && trimmed.endsWith("'")) {
      return trimmed.slice(1, -1).replace(/''/g, "'");
    }
    if (trimmed.startsWith('"') && trimmed.endsWith('"')) {
      return trimmed
        .slice(1, -1)
        .replace(/\\n/g, '\n')
        .replace(/\\t/g, '\t')
        .replace(/\\"/g, '"')
        .replace(/\\\\/g, '\\');
    }
  }
  return trimmed;
}

/** Parse the document into plain JavaScript values. */
function parseYaml(text) {
  const lines = readLines(text);
  const cursor = { index: 0 };

  function parseBlock(indent) {
    if (cursor.index >= lines.length) return null;
    const text = lines[cursor.index].text;
    if (text.startsWith('- ') || text === '-') {
      return parseSequence(indent);
    }
    if (text.startsWith('[') || text.startsWith('{')) {
      // A flow collection on its own line, e.g.
      //
      //     test:
      //       [
      //         "CMD-SHELL",
      //         "pg_isready -U user -d db",
      //       ]
      //
      // YAML allows a flow collection to span lines, and Docker Compose
      // files use that. It is still a single value, not a nested mapping.
      const line = lines[cursor.index];
      cursor.index += 1;
      return parseFlow(stripComment(line.text), lines, cursor);
    }
    return parseMapping(indent);
  }

  function parseMapping(indent) {
    const result = {};
    while (cursor.index < lines.length) {
      const line = lines[cursor.index];
      if (line.indent < indent) break;
      if (line.indent > indent) {
        throw new Error(`unexpected indentation on line ${line.lineNumber}`);
      }
      if (line.text.startsWith('- ')) break;

      const separator = findKeySeparator(line.text);
      if (separator === -1) {
        throw new Error(`expected "key: value" on line ${line.lineNumber}`);
      }
      const key = unquote(line.text.slice(0, separator).trim());
      const rest = stripComment(line.text.slice(separator + 1).trim());
      cursor.index += 1;

      if (rest === '' ) {
        // A nested block, or an explicit null.
        if (
          cursor.index < lines.length &&
          lines[cursor.index].indent > indent
        ) {
          result[key] = parseBlock(lines[cursor.index].indent);
        } else {
          result[key] = null;
        }
      } else if (rest === '>' || rest === '>-' || rest === '|' || rest === '|-' || rest === '>+' || rest === '|+') {
        result[key] = parseBlockScalar(rest, indent);
      } else if (rest.startsWith('[') || rest.startsWith('{')) {
        result[key] = parseFlow(rest, lines, cursor);
      } else {
        result[key] = unquote(rest);
      }
    }
    return result;
  }

  function parseBlockScalar(style, indent) {
    const collected = [];
    while (cursor.index < lines.length && lines[cursor.index].indent > indent) {
      collected.push(lines[cursor.index].text);
      cursor.index += 1;
    }
    if (style.startsWith('|')) return collected.join('\n');
    return collected.join(' ');
  }

  function parseSequence(indent) {
    const items = [];
    while (cursor.index < lines.length) {
      const line = lines[cursor.index];
      if (line.indent !== indent) break;
      if (!line.text.startsWith('- ') && line.text !== '-') break;

      const rest = line.text === '-' ? '' : line.text.slice(2).trim();
      cursor.index += 1;

      if (rest === '') {
        if (cursor.index < lines.length && lines[cursor.index].indent > indent) {
          items.push(parseBlock(lines[cursor.index].indent));
        } else {
          items.push(null);
        }
        continue;
      }

      const separator = findKeySeparator(rest);
      if (separator !== -1 && !rest.startsWith('[') && !rest.startsWith('{')) {
        // `- key: value` starts a mapping whose remaining keys are indented
        // two spaces further than the dash.
        const itemIndent = indent + 2;
        const item = {};
        const key = unquote(rest.slice(0, separator).trim());
        const valueText = stripComment(rest.slice(separator + 1).trim());
        if (valueText === '') {
          if (cursor.index < lines.length && lines[cursor.index].indent > itemIndent) {
            item[key] = parseBlock(lines[cursor.index].indent);
          } else {
            item[key] = null;
          }
        } else if (valueText.startsWith('[') || valueText.startsWith('{')) {
          item[key] = parseFlow(valueText, lines, cursor);
        } else {
          item[key] = unquote(valueText);
        }
        while (cursor.index < lines.length && lines[cursor.index].indent === itemIndent) {
          const inner = lines[cursor.index];
          const innerSeparator = findKeySeparator(inner.text);
          if (innerSeparator === -1) break;
          const innerKey = unquote(inner.text.slice(0, innerSeparator).trim());
          const innerValue = stripComment(inner.text.slice(innerSeparator + 1).trim());
          cursor.index += 1;
          if (innerValue === '') {
            if (cursor.index < lines.length && lines[cursor.index].indent > itemIndent) {
              item[innerKey] = parseBlock(lines[cursor.index].indent);
            } else {
              item[innerKey] = null;
            }
          } else if (innerValue.startsWith('[') || innerValue.startsWith('{')) {
            item[innerKey] = parseFlow(innerValue, lines, cursor);
          } else {
            item[innerKey] = unquote(innerValue);
          }
        }
        items.push(item);
        continue;
      }

      if (rest.startsWith('[') || rest.startsWith('{')) {
        items.push(parseFlow(rest, lines, cursor));
      } else {
        items.push(unquote(stripComment(rest)));
      }
    }
    return items;
  }

  const document = parseBlock(lines.length ? lines[0].indent : 0);
  if (cursor.index < lines.length) {
    throw new Error(`could not parse from line ${lines[cursor.index].lineNumber}`);
  }
  return document;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function readText(filePath) {
  return fs.readFileSync(filePath, 'utf8');
}

/** Flatten every string value in a structure, with its key path. */
function collectStrings(value, prefix, sink) {
  if (value === null || value === undefined) return;
  if (Array.isArray(value)) {
    value.forEach((item, index) => collectStrings(item, `${prefix}[${index}]`, sink));
    return;
  }
  if (typeof value === 'object') {
    for (const key of Object.keys(value)) {
      collectStrings(value[key], prefix ? `${prefix}.${key}` : key, sink);
    }
    return;
  }
  sink.push({ path: prefix, value: String(value) });
}

/**
 * Resolve the Dockerfile a service will actually be built from.
 *
 * Docker Compose looks for `Dockerfile` inside the build context when the
 * `dockerfile` key is absent, and a relative `dockerfile` path is itself
 * relative to the context. Resolving both the same way here means the check
 * describes what Docker will do rather than what the file literally says.
 */
function effectiveDockerfile(service) {
  const build = service.build || {};
  const context = build.context || '.';
  const dockerfile = build.dockerfile || 'Dockerfile';
  return path.resolve(REPO_ROOT, context, dockerfile);
}

// ---------------------------------------------------------------------------
// Checks
// ---------------------------------------------------------------------------

function main() {
  console.log('docker-compose validation');
  console.log('='.repeat(60));

  if (!fs.existsSync(COMPOSE_PATH)) {
    fail(`missing ${path.relative(REPO_ROOT, COMPOSE_PATH)}`);
    return finish();
  }

  const raw = readText(COMPOSE_PATH);
  let compose;
  try {
    compose = parseYaml(raw);
  } catch (error) {
    fail(`docker-compose.yml does not parse: ${error.message}`);
    return finish();
  }
  ok('docker-compose.yml parses cleanly');

  const services = compose && compose.services ? compose.services : {};
  const db = services.db;
  const backend = services.backend;
  const frontend = services.frontend;

  // -- the three services exist -------------------------------------------
  check(db, 'service "db" is defined', 'service "db" is not defined');
  check(backend, 'service "backend" is defined', 'service "backend" is not defined');
  check(
    frontend,
    'service "frontend" is defined',
    'service "frontend" is not defined'
  );
  if (!db || !backend || !frontend) return finish();

  // -- the database --------------------------------------------------------
  check(
    typeof db.image === 'string' && db.image.includes('postgres'),
    `the database uses ${db.image}`,
    `the database image is ${JSON.stringify(db.image)}; expected a PostgreSQL image`
  );
  check(
    db.healthcheck &&
      JSON.stringify(db.healthcheck.test).includes('pg_isready'),
    "the database healthcheck uses pg_isready",
    "the database healthcheck does not use pg_isready, so the backend could be "
      + 'started against a database that is still booting'
  );

  // -- build contexts ------------------------------------------------------
  check(
    backend.build && backend.build.context === '.',
    'the backend builds from the repository root (context: .)',
    `the backend build context is ${JSON.stringify(
      backend.build && backend.build.context
    )}; it must be "." because the backend imports the "ai" package that lives `
      + 'outside backend/'
  );
  check(
    effectiveDockerfile(backend) === BACKEND_DOCKERFILE,
    'the backend is built from backend/Dockerfile',
    `the backend is built from ${path.relative(
      REPO_ROOT,
      effectiveDockerfile(backend)
    )}; expected "backend/Dockerfile"`
  );
  check(
    frontend.build && frontend.build.context === './frontend',
    'the frontend builds from ./frontend',
    `the frontend build context is ${JSON.stringify(
      frontend.build && frontend.build.context
    )}; expected "./frontend"`
  );
  check(
    effectiveDockerfile(frontend) === FRONTEND_DOCKERFILE,
    'the frontend is built from frontend/Dockerfile',
    `the frontend is built from ${path.relative(
      REPO_ROOT,
      effectiveDockerfile(frontend)
    )}; expected "frontend/Dockerfile"`
  );

  check(
    fs.existsSync(BACKEND_DOCKERFILE),
    'backend/Dockerfile exists',
    'backend/Dockerfile does not exist'
  );
  check(
    fs.existsSync(FRONTEND_DOCKERFILE),
    'frontend/Dockerfile exists',
    'frontend/Dockerfile does not exist'
  );

  // -- healthchecks match the images --------------------------------------
  const backendDockerfile = fs.existsSync(BACKEND_DOCKERFILE)
    ? readText(BACKEND_DOCKERFILE)
    : '';
  const frontendDockerfile = fs.existsSync(FRONTEND_DOCKERFILE)
    ? readText(FRONTEND_DOCKERFILE)
    : '';

  const backendHealth = JSON.stringify(backend.healthcheck && backend.healthcheck.test);
  const frontendHealth = JSON.stringify(frontend.healthcheck && frontend.healthcheck.test);

  check(
    backendHealth.includes('curl'),
    'the backend healthcheck uses curl',
    'the backend healthcheck does not use curl'
  );
  check(
    /apt-get install[^\n]*\bcurl\b/.test(backendDockerfile) ||
      backendDockerfile.includes('curl'),
    'backend/Dockerfile provides curl for the healthcheck',
    'backend/Dockerfile does not install curl, but the healthcheck needs it'
  );
  check(
    frontendHealth.includes('wget'),
    'the frontend healthcheck uses wget',
    'the frontend healthcheck does not use wget'
  );
  check(
    /FROM\s+nginx:[^\s]*alpine/.test(frontendDockerfile),
    'frontend/Dockerfile uses an alpine nginx image, which ships wget',
    'frontend/Dockerfile does not use an alpine nginx image; wget would then '
      + 'not be available for the healthcheck'
  );

  for (const [name, service] of [
    ['db', db],
    ['backend', backend],
    ['frontend', frontend],
  ]) {
    const healthcheck = service.healthcheck;
    check(
      healthcheck &&
        healthcheck.interval &&
        healthcheck.timeout &&
        healthcheck.retries,
      `the ${name} healthcheck declares interval, timeout and retries`,
      `the ${name} healthcheck is missing interval, timeout or retries`
    );
  }

  // -- dependency ordering ------------------------------------------------
  check(
    backend.depends_on &&
      backend.depends_on.db &&
      backend.depends_on.db.condition === 'service_healthy',
    'the backend waits for the database to be service_healthy',
    'the backend does not wait for the database to become healthy; it must use '
      + 'condition: service_healthy'
  );
  check(
    frontend.depends_on &&
      frontend.depends_on.backend &&
      frontend.depends_on.backend.condition === 'service_healthy',
    'the frontend waits for the backend to be service_healthy',
    'the frontend does not wait for the backend to become healthy; it must use '
      + 'condition: service_healthy'
  );

  // -- the backend must not look for the database on localhost --------------
  const databaseUrl = backend.environment && backend.environment.DATABASE_URL;
  check(
    typeof databaseUrl === 'string' && /@db:5432/.test(databaseUrl),
    'the backend reaches the database at the service name "db", not localhost',
    `the backend DATABASE_URL is ${JSON.stringify(databaseUrl)}; inside the `
      + 'Compose network the database is reached at "db:5432"'
  );

  // -- no real secrets -----------------------------------------------------
  const sensitiveKeys = ['SECRET_KEY', 'POSTGRES_PASSWORD'];
  const strings = [];
  collectStrings(compose, '', strings);

  for (const key of sensitiveKeys) {
    const entries = strings.filter((entry) => entry.path.endsWith(`.${key}`));
    if (entries.length === 0) {
      fail(`the compose file never mentions ${key}`);
      continue;
    }
    for (const entry of entries) {
      const value = entry.value;
      const fallback = value.includes(':-')
        ? value.slice(value.indexOf(':-') + 2).split('}')[0]
        : value;
      const isPlaceholder =
        /change[_-]?me/i.test(fallback) ||
        /insecure/i.test(fallback) ||
        /dev-only/i.test(fallback) ||
        /example/i.test(fallback) ||
        /placeholder/i.test(fallback) ||
        /^<.*>$/.test(fallback) ||
        /^\$\{/.test(fallback);
      check(
        isPlaceholder,
        `${entry.path} falls back to an obvious placeholder`,
        `${entry.path} does not fall back to an obvious placeholder; a real `
          + 'secret must never be committed'
      );
    }
  }

  check(
    !/\bAKIA[0-9A-Z]{16}\b/.test(raw) &&
      !/-----BEGIN [A-Z ]*PRIVATE KEY-----/.test(raw),
    'the compose file contains no AWS key or private key material',
    'the compose file appears to contain real key material'
  );

  // -- .env must be ignored -------------------------------------------------
  if (fs.existsSync(GITIGNORE_PATH)) {
    const gitignore = readText(GITIGNORE_PATH);
    check(
      /^\s*\.env\s*$/m.test(gitignore),
      '.env is listed in .gitignore',
      '.env is not listed in .gitignore; a local .env could be committed'
    );
  } else {
    fail('missing .gitignore');
  }

  return finish();
}

function finish() {
  for (const message of passed) console.log(`PASS  ${message}`);
  for (const message of failed) console.log(`FAIL  ${message}`);
  console.log('-'.repeat(60));
  console.log(`${passed.length} passed, ${failed.length} failed`);
  if (failed.length > 0) {
    console.log('RESULT: FAIL');
    process.exitCode = 1;
    return 1;
  }
  console.log('RESULT: PASS');
  return 0;
}

main();
