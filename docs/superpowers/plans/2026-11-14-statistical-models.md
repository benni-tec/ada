# Statistical models and the patient pathway model: plan and brief for scientific grounding

> **Status (2026-11-14): built for lung cancer, v1, on the branch `pathway-model`; see the implementation plan's status. Part 4 is answered in `2026-11-14-statistical-models-grounding.md`, which revises the model in Part 2 (a DAG instead of a product of HRs; education and mother tongue as action flags only; screening dropped). Part 3's tasks are replaced by `2026-11-14-statistical-models-implementation.md`.** This document has two readers:
> 1. **A scientist (Fable)**, who grounds the model scientifically: read Parts 1, 2 and 4, and answer the questions in Part 4.
> 2. **The engineers**, who build the platform part: Part 3.
>
> Functions and scenarios, planned alongside this for population-level what-ifs, were abandoned on 2026-11-15 in favour of cases and models (`2026-11-15-cases.md`). The patient-level model is the resource described here.

## Part 1: What we are building and why

### The challenge, in one paragraph

The Junction 2026 challenge "Equal Care Across Finland" (AstraZeneca) asks how Finland can make cancer care equitable. Finland's National Cancer Strategy 2026–2035 sets targets, among them: five-year survival of poor-prognosis cancers at the Nordic level; treatment within target times; 70 % of cancers diagnosed at stage I–II; and 80 % screening participation in every wellbeing services county. The challenge organisers want **solutions at the level of the individual patient**, not only regional dashboards.

### What our data shows (all in ADA, project "Nordic cancer care")

- **Finland lags the other Nordic countries on survival.** NORDCAN 2020–2024: lung (17.9 % men / 30.8 % women in Finland, against 28–31 / 37–39 % elsewhere), pancreas and liver. The strategy targets the Nordic level, defined as the mean of Sweden and Norway.
- **Finland's pathways are slower.** Finland has no national cancer pathways and no cancer-specific waiting-time series. Denmark, Norway and Sweden have national pathways with standard times. In 2025, 77 % of Danish pathways were within the standard time; in 2024, 45 % of Swedish ones were within the lead time, against an 80 % target. Lung cancer, symptoms to treatment (unpublished study reported by Yle): about 155 days in Finland, 107 in Sweden, 67 in Denmark.
- **Inequity runs along the pathway** (Zai et al. 2025, BMJ Public Health, 469,522 Finnish patients, 2000–2019). Low education is associated with:
  - stage IV at diagnosis: OR 1.10 for men, 1.15 for women;
  - less surgery, radiotherapy and chemotherapy;
  - cancer mortality HR 1.13–1.14 after adjusting for stage and treatment.

  Patients entering via public primary care wait longer than those via occupational or private care: DLBCL symptoms to treatment, median 127 vs 76 days (Kuitunen et al.).

### The resource: a statistical model

ADA already has *pipelines* (operators over data sources, run and cached) and is getting *functions* (parameterised pipelines; see the functions plan). We add a third kind of resource, the **statistical model**:

1. **It is built from datasets, and its construction is explicit.** A model declares its structure (e.g. "relative survival, proportional hazards"), its **terms** (each factor, its coding, its reference level) and its **parameters** (coefficients, baseline tables). Every parameter has its provenance: either estimated from named ADA pipelines (with the snapshots pinned), or taken from a cited publication (with CI and a link to the ADA source holding it). Anyone can see exactly how the model is put together.
2. **It is evaluated on individual inputs.** E.g. one patient's attributes and pathway state. The evaluation returns the prediction, its uncertainty interval and **how each factor affects the outcome**: its contribution, and the counterfactual "if this factor were at its reference or benchmark level".
3. **Evaluations are never stored**, for privacy (patient data) and performance (thousands of interactive evaluations). No run, no snapshot, no operator, no log of the inputs. What persists is the model (versioned), never what it was applied to.

### First model: the patient pathway model

- **Input, one patient:**
  - **non-modifiable:** cancer site (confirmed or suspected), age, sex, education level, mother tongue (domestic / non-domestic language), wellbeing services county;
  - **modifiable or situational:** care route of first contact (public health centre / occupational / private / emergency); pathway position (which of the eight steps: symptoms → considering care → first contact → physician assessment → tests and referrals → diagnosis → MDT plan → treatment start), with the days spent in each completed step and the days elapsed in the current one; stage if known; screening attendance where the site has screening.
- **Output:**
  - predicted 5-year relative survival as things stand, with an interval;
  - the same if the remaining steps follow the Nordic benchmark (the Danish standard pathway times for that cancer);
  - the gain per action, ranked: which next step, done when, gains the most (e.g. direct imaging referral instead of a second primary-care visit; MDT within N days; treatment start within the standard time);
  - equity flags derived from the gradients: e.g. navigator support for low education, an interpreter for a non-domestic mother tongue, and attention to the public-route delay.
- **Purpose:** decision support and explanation of where *this* patient loses time and survival compared with a Nordic pathway. It is **not** a clinical prognosis tool for treatment decisions (see Part 4, questions on intended use).

## Part 2: Proposed model construction (to be grounded)

This is a first proposal from the data team. Every assumption here is a question in Part 4.

### Structure

Relative survival under proportional hazards on the excess-hazard scale:

```latex
S_i(5) = S_0(5 \mid \text{site}, \text{sex}, \text{age band})^{\,\prod_k HR_k(x_{ik})}
```

`S_0` is the Finnish baseline: 5-year relative survival for the site, sex and age band (NORDCAN, Finland, 2020–2024; the age-specific survival route). Each `HR_k` is the hazard ratio of factor `k` at the patient's level against the baseline population's mix, so that the population-average patient reproduces `S_0`. That means the HRs must be centred on the Finnish population distribution of each factor, which needs that distribution.

### Terms and candidate parameters

| Term | Coding | Candidate parameter | Source (in ADA unless noted) |
| --- | --- | --- | --- |
| Site × sex × age band | baseline table | Finnish 5-year relative survival | NORDCAN 9.6.1 (survival route; age-specific route still to add) |
| Education | basic / secondary / tertiary | cancer-specific mortality HR low vs high 1.13 (men), 1.14 (women), adjusted for stage and treatment; per site where reported (e.g. breast 1.19, lung (women) 1.22) | Zai et al. 2025 |
| Education (survival, colorectal) | basic / secondary / high | relative excess risk 0.72 (men), 0.76 (women), high vs basic | Finke et al. 2021 |
| Time to treatment | weeks beyond the benchmark | HR per 4-week delay: surgery 1.06–1.08 (breast 1.08; colectomy 1.06), radical radiotherapy head and neck 1.09, systemic therapy 1.01–1.28 by indication | Hanna et al., BMJ 2020 (in the literature; to register) |
| Care route | public / occupational-private | days added to symptom-to-treatment (DLBCL: 127 vs 76 median), turned into HR through the time term | Kuitunen et al. (lymphoma only) |
| Stage | I–IV or localised / non-localised | stage-specific survival (e.g. Norway lung stage I 71 %, stage IV 9 %); Finnish stage unknown in 61 % | Norwegian Cancer Registry (to add); IHE / Finnish Cancer Registry |
| Stage given education | OR of stage IV | 1.10–1.30 by site | Zai et al. 2025 |
| Screening attendance | attended / not | breast cancer death RR 0.67 (0.49–0.90) for attenders, Finland; self-selection RR 1.56 for non-attenders | Br J Cancer 2016; Sarkeala et al. 2008 (to register) |
| Nordic benchmark pathway | standard days per step and site | Danish standard pathway times (kræftpakkeforløb) | Sundhedsstyrelsen (to add) |

### Uncertainty and explanation

- **Uncertainty:** draw each parameter from its sampling distribution (log-normal for ratios, from the CI), evaluate N times and report the 2.5th–97.5th percentiles. This is done at evaluation and not stored.
- **Factor effects, per evaluation:**
  - each term's contribution on the log-hazard scale;
  - the counterfactual survival with that term at its reference (non-modifiable) or at the benchmark (modifiable);
  - a ranking of the modifiable levers by gain;
  - a sensitivity check: how much each parameter's CI moves the prediction.

### Validation ideas (to be grounded)

- **Calibration in the large:** the population-average Finnish patient reproduces `S_0` per site and sex.
- **Nordic check:** applying Danish pathway times to the average Finnish patient should move Finnish survival *towards* the Nordic level. How much of the gap it closes is itself a finding: the rest is unexplained by timing.
- **Natural experiment:** Denmark (2007–2009), Norway (2015) and Sweden (2015–2016) introduced pathways, Finland did not. Difference-in-differences on NORDCAN survival by site gives an independent estimate of the pathway effect, to compare with the effect-size route.
- **Equity check:** the model's predicted gap between low- and high-education patients against the Cancer Registry's observed mortality ratios (in ADA: basic vs tertiary RR by cancer and sex, 2019–2023).

## Part 3: The platform (engineering)

### Resource model

- `StatisticalModel{id, project_id, name, description, kind, latest_version}`.
- `ModelVersion{model_id, version, structure, outcome, terms, parameters, baseline: [{operator_id, snapshot_ids}], provenance, validation, created_by, created_at}`. It is immutable; a change makes a new version.
  - `structure`: e.g. `relative_survival_ph`, later also `logistic`, `linear` or `poisson_rate`.
  - `outcome`: e.g. 5-year relative survival.
  - `terms`: name, type (categorical / numeric / duration), levels or range, reference, modifiable or not, description.
  - `parameters`: per term and level, an estimate, CI or distribution, and provenance (an ADA operator with pinned snapshot, or a cited source id plus the passage it was checked against).
  - `validation`: the results of the checks above, stored as figures with their operators.
- **Built from datasets:**
  - *estimated* parameters come from a named ADA operator. Building the version pins the snapshots it read, so the version is reproducible.
  - *cited* parameters come from an ADA source holding the published figure (as for Zai, OECD and Finke today).
  - Both kinds show in the model's lineage.

### Evaluation (never stored)

- **API:**
  - REST `POST /api/models/{id}/versions/{v}/evaluate` with `{inputs: {term: value}, draws?: int, explain?: bool}`;
  - MCP `evaluate_model(model_id, version?, inputs, session_id)`.

  Both return `{prediction, interval, contributions[], counterfactuals[], levers[], warnings[]}`.
- **Nothing persists:**
  - no run, snapshot, operator, session entry content or log line contains the inputs;
  - the MCP session records only that a model was evaluated, with the model and version, never the inputs or the result. This is the one exception to "every tool call is recorded in its session";
  - responses carry `Cache-Control: no-store`;
  - a request log keeps the route and timing, not the body.
- **Performance:** a version compiles to an in-memory form at first use: baseline tables loaded once and parameters as arrays. An evaluation with 2,000 draws is vectorised (NumPy) and takes well under 100 ms, with no DuckDB run per evaluation.
- **Validation of inputs:** against the terms (types, levels, ranges). Unknown terms are refused, and missing optional terms use the reference with a warning.

### Interfaces

- **MCP:** `create_model` (from a construction spec), `list_models`, `get_model` (structure, terms, parameters, provenance, validation), `evaluate_model`. Agents may evaluate synthetic or user-provided profiles; the instructions say never to put real personal data into any other tool.
- **Frontend:**
  - a *Models* page listing each model's terms, parameters with sources and CIs, and validation;
  - an **evaluation form** (one field per term, levers as sliders);
  - the result as survival now vs at Nordic timing with intervals, a factor-contribution chart (waterfall on the log-hazard scale, or survival differences), and ranked levers.

  The form state lives in the browser only.
- **Widgets:** a widget may show a model's *structure* (parameters, validation) like any operator output. Evaluations are not widgets, because widgets persist.

### Tasks (sketch)

1. Model and version storage, construction spec, provenance (migration `0015` or the next free number).
2. Compiler and vectorised evaluator; draws; contributions; counterfactuals; levers.
3. Ephemeral REST and MCP evaluation; session middleware exception; no-store; tests that nothing is written.
4. Models page and evaluation form.
5. Data work: the missing sources (age-specific survival, stage-specific survival, Danish standard pathway times, the effect-size papers); build the patient pathway model v1; run the validation checks; synthetic example patients for the demo.

## Part 4: Questions for scientific grounding (Fable)

Please answer each with a recommendation, the evidence (papers with links), and the residual risk.

### A. Model structure

1. Is relative survival with proportional hazards on the excess-hazard scale the right frame for combining published HRs (most estimated on overall or cancer-specific mortality) with relative-survival baselines? Which conversions are defensible (cancer-specific HR as excess-hazard HR)?
2. Is multiplying HRs from different studies defensible? Education, stage, treatment and delay are causally related: education acts partly *through* stage and delay. Zai's mortality HR is adjusted for stage and treatment. How do we avoid double counting? Should the model be a causal chain (education → route → delay → stage → survival) rather than a product of marginal HRs?
3. Five-year horizon and age bands: what is the right granularity for NORDCAN's age-specific survival, and how do we centre HRs on the Finnish factor distribution?

### B. Time to treatment

4. The waiting-time paradox: sicker patients are treated faster, which biases naive delay–survival estimates. Does Hanna et al. (BMJ 2020) handle it well enough to apply its per-4-week HRs prospectively to one patient's remaining pathway? Are there better site-specific estimates for lung, pancreas and liver (the strategy's poor-prognosis cancers), where delay effects are least studied?
5. Does delay act through stage progression (a stage-shift model) or directly? Which is better supported, by site?
6. Danish standard pathway times per site and step: what are the current values, and which step definitions map to the eight steps in the challenge handout?

### C. Transportability

7. Can Danish, Norwegian and Swedish pathway effects (DiD on NORDCAN) be transported to Finland? What confounders (new treatments, coding changes, registry practice, stage completeness) must the DiD control for?
8. Finland's stage is unknown for 61 % of cases. How should a model use stage when it is usually missing (multiple imputation, a stage-free baseline, sensitivity bounds)?

### D. Equity terms

9. Education, mother tongue and care route: which effects are robustly estimated in Nordic populations, and which are proxies we should not put into an individual model? Is it ethical to output a lower predicted survival for a low-education patient, or should equity factors only drive *actions* (navigator, interpreter) and not the prognosis shown?
10. Screening attendance at the individual level: how do we correct for self-selection (non-attenders' excess risk) in an individual prediction?

### E. Validation and intended use

11. Which validation is feasible without individual data: calibration in the large, Nordic convergence, DiD comparison, equity ratios? Is any external validation possible (published Nordic individual-level models)?
12. Intended use and regulation: as decision support that ranks pathway actions, does this fall under the EU MDR (software as a medical device) or the EU AI Act high-risk category? What wording and limits keep it within "population-informed pathway guidance" for the hackathon demo?
13. Uncertainty communication: how should intervals and per-factor effects be shown to a clinician or navigator so they are not over-read?

## Sources already in ADA (for reference)

NORDCAN survival, incidence and mortality by site (Nordic, 2010–2024; survival 1967–2024); Zai et al. 2025 (extract); OECD/EU Country Cancer Profile Finland 2025 (screening by education, employment, language); Finke et al. 2021; Kuitunen et al. (DLBCL); Cancer Registry "Cancer in Finland 2023" ch. 13 (mortality by education); IHE Cancer Dashboard Finland 2026 (stage, Nordic lung waits); Danish pathway report 2025 (regional shares); Swedish SVF report 2024; Cancer Registry lung report 2024 (treatment by county, OCR); Sotkanet county indicators (screening, risk factors, survival, patient experience).

Literature found but not yet registered:
- Hanna et al., "Mortality due to cancer treatment delay: systematic review and meta-analysis", BMJ 2020 (https://www.bmj.com/content/371/bmj.m4087);
- Finnish breast screening effect, Br J Cancer 2016 (https://www.nature.com/articles/bjc201668.pdf);
- Dibden et al., worldwide cohort meta-analysis of mammography screening, 2020 (https://pmc.ncbi.nlm.nih.gov/articles/PMC7226343);
- Khalife et al., Nordic lung cancer care comparison, Acta Oncologica 2025 (https://pmc.ncbi.nlm.nih.gov/articles/PMC12160590/);
- Seppä et al., variation in survival between and within hospital districts, Acta Oncologica 2020 (https://medicaljournalssweden.se/actaoncologica/article/view/24148).
