# UP-Fall Detection Dataset — Decision Record (Rejected)

> Status: **considered and rejected.**
> **NOT downloaded. NOT used. No model uses it.** No metric in this project was
> produced from it. This file exists only to record *why* the choice changed.

This is a **decision record, not a usage guide.** There is no preprocessing
recipe here, no split, no features — because none were ever written. If you are
looking for how to use UP-Fall, this document will disappoint you on purpose.

---

## 1. The decision, in one paragraph

UP-Fall was the project's **first choice** for the fall-detection model. It was
selected in the original plan, and it is still recorded in the codebase:
`dataset_registry` has a CHECK constraint allowing the slug `up_fall`, and
`ai/registry.py` names it in the comment explaining why fall detection uses a
different dataset. It was then **rejected**, because the full distribution is
**~812 GB**, which is impractical to download and process for a graduation
project running on a single machine. **[SisFall](sisfall.md)** was used instead.

## 2. What UP-Fall is

| Field | Value |
|---|---|
| **Name** | UP-Fall Detection Dataset |
| **Kind** | Publicly released research dataset — **multi-modal** fall detection: wearable sensors, ambient sensors, and vision devices |
| **Citation** | Martínez-Villaseñor, L. A.; Ponce, E. V. et al. — *"UP-Fall Detection Dataset: A Multimodal Approach"*, **Sensors**, 2019 |
| **Source URL** | The publisher's dataset page (linked from the paper). **To verify** the current canonical URL before any download attempt. |
| **Size** | **~812 GB** — the figure recorded in this repository (top-level [README](../../README.md#datasets) and `ai/registry.py`). The publisher's own abstract quotes "more than 850 GB of information" from wearable, ambient and vision devices, so the two numbers are close but not identical. **To verify** against the publisher's page. |
| **Licence** | **To verify** — confirm the terms with the authors before downloading or redistributing anything. |
| **Checksum** | **To verify** — no download has taken place, so there is nothing to hash. |

## 3. Why it was rejected

| Reason | Detail |
|---|---|
| **Volume** | The complete distribution is ~812 GB. Downloading it is not a "click a link" operation; it is a multi-day transfer that competes for the same disk and bandwidth the rest of the project needs. |
| **Processing cost** | A multi-modal dataset has to be decoded across several sensor modalities, aligned in time, and windowed. Doing that at that volume on a student laptop is not a realistic part of a graduation project. |
| **Storage in git-ignored space** | Even if downloaded, it would live in `data/raw/`, which is git-ignored — correct for the project, but it would still have to be re-acquired by every person who clones the repository. |
| **No alternative value** | The same research question — *can a wearable accelerometer signal identify a fall?* — is answerable with a dataset that is two orders of magnitude smaller. See §5. |

> **What was actually replaced.** The decision was not "no fall detection". It
> was "this dataset, at this size, is not affordable here — find one that is".

## 4. Status, stated plainly

| Question | Answer |
|---|---|
| Has the archive been downloaded? | **No.** |
| Has any file of it been parsed? | **No.** |
| Does any model in this project use it? | **No.** |
| Are there metrics from it anywhere in this repository? | **No.** |
| Is any of it committed to git? | **No** — and nothing to commit, since nothing was fetched. |
| Is it referenced in code? | Only as a **decision**: the `up_fall` slug in `dataset_registry`'s CHECK constraint, and a comment in `ai/registry.py` recording why it was not used. |
| Why keep the file at all? | So the next person does not re-litigate the same choice, and so the record shows that a dataset was rejected **before** being downloaded rather than after wasting the disk. |

## 5. What replaced it, and on what grounds

**[SisFall](sisfall.md)** — a single-modality accelerometer dataset that is
roughly 232 MB, was downloaded and used to train the fall-detection model in
`ai/fall_detection/`, and already produces a measured, published result. (The
archive itself is git-ignored and is not in the working tree; see
[sisfall.md §3](sisfall.md).)

| Trade-off | UP-Fall | SisFall (chosen) |
|---|---|---|
| Size | ~812 GB | 232,407,821 bytes |
| Modalities | Wearable + ambient + vision | Accelerometer only |
| Elderly fall data | Present, more of it | Only **one** elderly subject simulates falls |
| Practical here | No | Yes — already done |
| Comparability | Stronger benchmark | Weaker, and honestly labelled as such |

The honest summary of that trade-off: **SisFall gave up elderly-subject
coverage and multimodal context in exchange for a result that exists at all.**
The elderly weakness is documented in [sisfall.md §8](sisfall.md) rather than
hidden, and it is the strongest argument for revisiting this decision if more
time or storage becomes available.

## 6. What would have to change to revisit it

Nothing here is a plan — it is the checklist that made the original decision
defensible, so a future reader can judge whether it still holds:

1. Storage and time for a ~812 GB download, plus the disk to extract and
   process it.
2. A confirmed licence from the authors.
3. A decision about which modalities to use. Using one modality of a
   multi-modal dataset throws away most of what makes it large; using all of
   them is the cost that made it impractical in the first place.
4. A subject-wise split agreed in advance, and enough elderly fall subjects to
   say anything about the elderly cohort.

## 7. See also

- [SisFall](sisfall.md) — the dataset that is actually used.
- [Datasets index](README.md) — the index and the rules.
- [`ai/registry.py`](../../ai/registry.py) — where the decision is recorded in code.
