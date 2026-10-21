# CASAS — Smart-Home Activity Data for Behavioural Analysis

> Status: **planned — NOT downloaded, NOT used.**
> No model uses this dataset yet. The planned consumer, `ai/behavioral_analysis/`,
> exists **only as a documented placeholder** (`__init__.py` + `README.md`) —
> there is no `preprocess.py`, no `train.py` and no `predictor.py` — so the API
> answers behavioural-anomaly requests with **HTTP 503** and code
> `MODEL_NOT_LOADED`.

This document exists because behavioural analysis is the part of this project
most likely to be *misread*. A model that says "today looks different from your
usual day" is a **hint to a caregiver**, not a diagnosis, and the dataset it
learns from — a smart home full of sensors — is exactly the kind of data that
makes it tempting to over-claim. So the dataset is documented first, and its
licence, size and shape are written down before anybody downloads it.

---

## 1. Identity

| Field | Value |
|---|---|
| **Name** | CASAS smart-home datasets (the "CASAS" project, Washington State University) |
| **Kind** | Publicly released research datasets — long-term ambient smart-home sensor data with human activity annotations |
| **Citation** | Cook, D.; Crandall, A.; Thomas, B.; Krishnan, N. — *"CASAS: A smart home in a box"*, **IEEE Computer** 46(7):62–69, 2013 |
| **Dataset catalogue** | `https://casas.wsu.edu/datasets` |
| **Alternative host** | The same research group published a related collection in the UCI Machine Learning Repository: Cook, D.; Crandall, A.; Thomas, B. (2012) — *Human Activity Recognition from Continuous Ambient Sensor Data*, which the repository lists under **CC BY 4.0**. **To verify** whether the chosen sub-dataset is available there, and under what terms. |
| **Source URL** | The catalogue above. **To verify** the direct download URL for the specific sub-dataset once one is chosen — the catalogue contains many, and they are **not** interchangeable. |
| **Licence** | **To verify.** Terms differ per sub-dataset and per host; the catalogue page is the authority. Confirm before downloading or redistributing anything. |
| **Version / date** | Individual sub-datasets carry their own collection dates (e.g. the longitudinal apartment collections span several years). **To verify** for the chosen sub-dataset. |
| **Size** | **To verify** — depends entirely on which sub-dataset is chosen. |
| **Checksum (SHA-256)** | **To verify** — no download has happened, so there is nothing to hash. |
| **Used by** | **Nothing yet.** The planned consumer is `ai/behavioral_analysis/` (see §7). |

---

## 2. What the data looks like

CASAS is a **smart-home** sensor platform: homes instrumented with low-level
ambient sensors that report events continuously, plus annotations describing
what the occupant was doing.

| Property | Value |
|---|---|
| **Sensors** | Motion/PIR detectors, magnetic door sensors, temperature sensors, light switches and relay/power sensors, over a ZigBee mesh with a USB gateway |
| **Event record** | One line per sensor event: timestamp, sensor identifier, message — sensor ids are room-qualified (e.g. `Bedroom`, `Bathroom`, `Kitchen`, `OfficeChair`, with a trailing letter to disambiguate same-type rooms) |
| **Labelling** | For annotated homes, a separate annotation file (e.g. `csh101.ann.txt`) maps the sensor stream onto named activities; the UCI-hosted collection additionally ships a feature-vector CSV per home built from a sliding window of **30 sensor events** |
| **Volume** | Long, continuous, longitudinal collection — the point of the dataset is *weeks and months* of ordinary home life, not isolated episodes |
| **Derived features** | Activity sequences and per-day aggregates (sensor-event counts, room-occupancy counts, first/last activity of the day, dwell time per room) |

---

## 3. Why it suits a per-resident routine baseline

The behavioural question this project asks is: **"is this day unusual for this
person?"** That question needs exactly what CASAS has and what a fall-detection
dataset does not:

- **Long enough to learn a routine from.** A baseline needs many ordinary days.
  CASAS provides weeks to years of them; a fall dataset provides seconds.
- **Low-level and continuous.** Ambient sensors produce an unbroken event
  stream, so "no motion in the kitchen all morning" is *visible* — the kind of
  signal a routine model can be built on.
- **Per home, not per activity.** Each home is effectively one household, so the
  "resident" in the model is the home. That maps directly onto the project's
  **per-resident baseline** design.
- **Annotated**, so the model's output can be checked against what people were
  actually doing, instead of being self-referential.

**The caveat that comes with it:** the occupants of CASAS homes are not
necessarily elderly, and the homes are instrumented research homes, not the
homes of the people this project monitors. A baseline learned here transfers to
an elderly resident only as a *method*, never as a *threshold*.

---

## 4. Intended approach

Not written yet. The plan, mirroring `ai/fall_detection/`:

1. **Ingest** the event stream and the activity annotations, per home.
2. **Aggregate to a per-resident baseline**: for one home, summarise each day
   as an activity sequence (which activities, in what order, at what times) plus
   simple per-day counts — the kind of features a caregiver could also read.
3. **Model the deviation** with one of:
   - an **IsolationForest** over the per-day feature vectors, or
   - **plain statistics** over the activity sequences (e.g. how unusual is
     today's transition pattern for this household).
4. **Score and threshold**: output a **deviation score**, a **stated threshold**,
   and the features that moved. Below the threshold, nothing happens.
5. **Document the false-positive rate**, measured on held-out homes/days, and
   publish it next to the model.

The rule that governs the whole design: **a routine change is usually benign.**
A person who is ill often rests more; a person who is fine also sometimes
stays in bed. The output is therefore a *prompt to look*, never a verdict.

---

## 5. The honest caveat — this is not a diagnosis

This is the most important paragraph in this document.

| The model outputs | The model does **not** output |
|---|---|
| A **behavioural deviation score** — how far today departs from this person's own baseline | A diagnosis, a disease, or a risk score |
| A **stated threshold** above which a caregiver is prompted to look | A claim that something is wrong |
| The **features that deviated**, so the reason is visible | A "healthy"/"unhealthy" verdict |
| A **documented false-positive rate**, so the cost of noise is known | A silent number that looks certain |

Three project rules apply directly to this capability:

1. **A missing measurement is not an emergency.** A quiet sensor, a day with no
   events, or an absent baseline must never escalate. In this project that rule
   is implemented as a hard severity cap on data gaps
   (see [alert-rules-and-kpis.md](../alert-rules-and-kpis.md)).
2. **An unavailable capability says so.** Until this model exists, the API
   returns `503 MODEL_NOT_LOADED` — not a score.
3. **Never present simulated data as real.** Any result derived from CASAS is
   research data about someone else's home, so it is flagged `is_simulated: true`
   and can never be shown as a resident's own behaviour.

---

## 6. Local location

| What | Path | Committed? |
|---|---|---|
| Downloaded archive | `data/raw/<chosen-sub-dataset>.zip` — **name To verify** | ❌ **No** — `data/raw/**` is git-ignored |
| Extracted data | `data/raw/<chosen-sub-dataset>/` | ❌ **No** |
| Derived features / baselines | `data/processed/` | ❌ **No** — `data/processed/**` is git-ignored |
| Trained model artefacts | `ai/models/behavioral_analysis/` | ❌ **No** — `ai/**/models/` is git-ignored |

---

## 7. What will consume it

| Item | State |
|---|---|
| `ai/behavioral_analysis/` (preprocess → train → predictor) | **Placeholder only.** The package exists with `__init__.py` and a `README.md` that states the plan; `preprocess.py`, `train.py` and `predictor.py` do **not** exist yet. It should follow the structure of `ai/fall_detection/`. |
| `ai/registry.py` | The third capability is registered under the key **`anomaly_detection`** and is currently an `UnavailablePredictor`; the planned module directory is `ai/behavioral_analysis/`. The two names differ deliberately — the module is named after the *analysis*, the registry key after the *kind of result*. |
| API today | `GET /api/v1/ai/predictors` reports `is_ready: false` for anomaly detection. `POST /api/v1/ai/predictors/anomaly_detection/check` returns **HTTP 503** with code **`MODEL_NOT_LOADED`**. |
| API after training | The predictor becomes a real one. Its result carries `source="imported_dataset"` and therefore `is_simulated: true`. |

---

## 8. Open questions before downloading

| # | Question | Status |
|---|---|---|
| 1 | Which **sub-dataset**? The catalogue contains many collections with very different lengths, sensor sets and annotation quality. This choice drives everything else. | **To decide** |
| 2 | Does the chosen collection carry **activity annotations**, or only raw sensor events? An unlabelled collection cannot train or validate anything. | **To verify** |
| 3 | Licence terms for the chosen sub-dataset and host. | **To verify** |
| 4 | Exact size in bytes and the SHA-256 checksum. | **To verify** |
| 5 | How many ordinary days per home are needed before a baseline is worth computing — and what happens for a resident with only a few days of history? | **To decide** |

---

## 9. See also

- [Datasets index](README.md) — the index and the rules.
- [UCI HAR](uci-har.md) — the planned dataset for activity recognition.
- [`ai/behavioral_analysis/README.md`](../../ai/behavioral_analysis/README.md) — the module's own statement of the plan and of what is missing.
- [Alert rules and KPIs](../alert-rules-and-kpis.md) — where the "missing data is not an emergency" rule is implemented.
- [CONTRIBUTING.md](../../CONTRIBUTING.md#open-tasks) — task **T2**, which this dataset serves.
