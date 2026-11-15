# Patient pathway model: scientific grounding, challenged assumptions and references

> **Status (2026-11-14, revision 3): review of `2026-11-14-statistical-models.md`, Parts 1, 2 and 4. Nothing is implemented.** This document answers the thirteen questions in Part 4, states what the model teaches and to whom, and ends with a revised specification (v2) and a reference list. The implementation plan built on it is `2026-11-14-statistical-models-implementation.md`.
>
> **What changed in revision 3.** The baseline is now the **Nordic level** (Norway and Sweden), not Finland, so "on target" is the strategy's own benchmark and no recalibration is needed. The patient-level output leads with the **fast-track trigger and the deadlines** of the Nordic pathways, which are exact, and puts survival second. The pre-diagnostic delay has one mechanism (a direct per-day effect, never skipped). The 16-week cap, Heiden's clock, the stage coding and the equity check are corrected. The Nordic difference-in-differences is dropped.
>
> **How the references were checked.**
> - 📖 the full text or the official page was read on 2026-11-14. Numbers are quoted from it.
> - ✓ the citation was confirmed by a web search; only the abstract was read.
> - ○ a standard reference cited from memory: check the DOI before it goes on a slide.

## What the model teaches, and to whom

**At the point of care, the model is a clock.** Norway and Sweden start a cancer pathway from a defined trigger ("well-founded suspicion") and give every step a deadline. Finland has no national trigger and no standard times. The tool tells a nurse, a GP or a pathway coordinator three things that need no hazard ratio: whether this presentation would start a lung-cancer pathway in Norway and Sweden, when the clock would have started, and when each step is due. Urgency comes from the deadline, not from a survival figure. A survival figure of "21 now, 23 on target" reads as small to a clinician and rests on the weakest evidence in the model, so it is shown second and graded.

**At the system level, the model is an accounting of the gap.** Starting from the Nordic survival for a profile and adding Finland's extra days gives how much of the Finnish shortfall timing can explain. For lung cancer in men, a rough calculation (Nordic level about 29 %, Finland 18 %, 88 extra days at Hanna's rate) takes 29 down to about 23. The remaining 23 → 18 is what the model does not explain: treatment access, stage mix, smoking and registry practice, but also any timing effect the model leaves out or misestimates (the published delay effects are averages from other countries). That residual is shown as a number, not hidden. "At the published rates, timing accounts for roughly half the gap" is a model-dependent estimate under the stated assumptions, not a measurement; the other half is the argument against treating faster pathways as the whole answer.

**Three further learnings, from the data already in ADA and the papers read:**
1. **Most of Finland's lost days are before diagnosis.** Lung, symptoms to treatment: about 155 days in Finland, 107 in Sweden, 67 in Denmark (Yle MOT 2025 ✓, unpublished study). Of the Finnish 155, more than 50 are the patient interval, 41 primary care and 58 specialised care. Only 40–60 % of Finnish patients with lung symptoms see a doctor at first contact, against 80–100 % elsewhere in the Nordics, and the wait for a health-centre appointment is about 14 days against 2–7 (Khalife 2025 📖, a survey of 42 clinicians). Those are system fixes: appointment access, nurse triage that can order imaging, direct CT from primary care.
2. **The education gap survives adjustment for stage and treatment** (Zai 2025 📖: cancer-specific mortality HR 1.13–1.14; Pokhrel 2010 📖). The response is support, not a different prognosis.
3. **Pathways coincide with large survival gains, with a lead-time caveat.** After Denmark's pathways, 3-year relative survival of lung cancer among symptomatic primary-care patients rose from 11.3 % to 20.4 %, excess hazard ratio 1.30 (1.09–1.55) before vs after, adjusted for stage, comorbidity, education and income (Jensen 2017 📖). The authors name lead time and recommend mortality as the better measure.

## The fast-track trigger and the deadlines

The patient-level centrepiece. Two of the three Nordic standards were read in full; Denmark's is still to load.

### Norway (Helsedirektoratet, *Pakkeforløp for lungekreft*, last revised 3 July 2026 📖)

- **Trigger ("begrunnet mistanke"):** radiology showing a malignancy-suspect change in the lung, or a biopsy from another organ showing cancer of probable lung origin.
- **Standard times (normative, calendar days):**
  - referral received → first visit at the investigating department: **7**;
  - first visit → work-up complete (decision): **21**;
  - work-up complete → start of treatment: **14** for surgery or radiotherapy, **7** for drug treatment;
  - referral received → start of treatment: **42** (surgery, radiotherapy), **35** (drugs).

### Sweden (RCC, *Standardiserat vårdförlopp lungcancer*, version 1.4, 2024-11-05 📖)

- **Two stages.** First, **suspicion ("misstanke")**, which sends the patient to imaging:
  - new airway symptoms (cough, breathlessness) for 6 weeks in a smoker or ex-smoker over 40;
  - chest or shoulder pain without another explanation;
  - haemoptysis.

  Then **well-founded suspicion ("välgrundad misstanke")**, which starts the pathway:
  - an imaging finding suggesting lung cancer;
  - a metastasis suggesting lung cancer;
  - repeated haemoptysis without another obvious cause, even with a normal X-ray;
  - superior vena cava obstruction;
  - recurrent laryngeal nerve palsy.

  An unclear X-ray with low suspicion is not well-founded suspicion; the patient goes to CT instead.
- **Primary-care times** (optimal, calendar days): referral decision → referral received 1; → X-ray or CT 5; → report to the referrer 1; → decision on well-founded suspicion 3; → pathway referral received 1. **Suspicion to pathway start: 11 days.**
- **National lead times** from the decision on well-founded suspicion to first treatment: **40** (drugs), **44** (surgery or radiotherapy), **30** (palliative). Goal: 80 % within the time.

### Denmark (Sundhedsstyrelsen, *Pakkeforløb for lungekræft*) ✗

Not read: sst.dk refuses automated access (HTTP 429). Download by hand. Its structure is the same (referral → first visit → work-up → treatment), and the model takes it as a third source for the median.

### Finland

No national trigger, no standard times, no cancer-specific waiting-time statistics. Primary-care access: see Khalife 2025 above.

### How the tool uses them

- **Stage 1, at first contact:** does the presentation meet the suspicion criteria (Swedish list; Norway's entry page gives similar guidance for smokers over 40)? If yes: imaging is due within the Swedish filter time (6 days to the image, 11 to the pathway decision).
- **Stage 2, at the trigger:** does it meet well-founded suspicion (Norwegian and Swedish lists, which agree on imaging and metastasis; Sweden adds three clinical signs)? If yes, the clock starts, and each deadline is the **median of the countries that define the step** (Norway and Sweden now, Denmark when loaded). Treatment start: Norway 42, Sweden 44 → **43 days** from the trigger for surgery or radiotherapy.
- **Output:** "would start a pathway in Norway and Sweden"; the clock start; each deadline with its status (met, late by *n*, due in *n*, overdue by *n*); the next action. The criteria lists are shown, with the country each comes from.
- **This is the exact part of the model.** It needs no effect size and carries no lead-time problem.

## Full-text check (2026-11-14)

| Paper or source | Read | What it settled |
| --- | --- | --- |
| Helsedirektoratet, pakkeforløp lungekreft (2026) | 📖 | Trigger and standard times as above. "Normative"; the legal basis stays the patient-rights act. |
| RCC, SVF lungcancer v1.4 (2024) | 📖 | Suspicion and well-founded-suspicion criteria, primary-care times, national lead times, as above. |
| Hanna 2020 (PMC7610021) | 📖 | **No pancreas or liver indication** (bladder, breast, colon, rectum, lung, cervix, head and neck only). **Lung surgery HR 1.06 (0.93–1.19), not significant**; NSCLC adjuvant chemotherapy 1.01 (0.99–1.04). Colectomy 1.06 (1.01–1.12); colorectal adjuvant chemotherapy 1.13 (1.09–1.17). Delay runs from diagnosis to first treatment. Outcome: overall survival. 25 of 34 studies are from the US. Log-linearity holds only **between 4 and 16 weeks of total delay**; the HRs must **not be used to find a minimal safe delay**. |
| Zai 2025 (PMC12551501) | 📖 | 469,522 cases (2000–2019, age 30+). **Stage missing in 30.0 %**, not 61 %; missingness does not differ by education. **Pancreas not analysed.** HRs are cancer-specific, adjusted for age, year, stage, treatment, birth year, marital status, origin, region and urbanisation. Lung HR for women only (1.22, 1.12–1.33). Stage IV (vs I–III) ORs: breast 1.30, prostate 1.21, colorectal 1.09–1.10; lung only in a figure. **Mother tongue not analysed.** |
| Pokhrel 2010 (PMC2965870) | 📖 | Cause-specific 5-year survival by education, 1996–2005. Lung: women 18.8 vs 12.3 %, men 10.6 vs 9.2 % (high vs basic). Stage adjustment attenuated the gradient only modestly. 8–10 % of deaths in the first 5 years avoidable at the high-education level. |
| Jensen 2017 (PMC5585953) | 📖 | Lung 3-year RS 11.3 % → 20.4 % after the Danish pathways; EHR 1.30 (1.09–1.55), adjusted for stage. Pathway-referred vs not: 0.77 (0.62–0.95). Lead time named; mortality recommended. |
| Sud 2020 (PMC7237184) | 📖 | **Not a stage-shift model.** A per-day "fatality HR" applied to survival: 0.0030 per day for good-prognosis tumours, 0.0056 otherwise, derived for three tumour types and assigned by survival class. No CI; varied ±8 % in sensitivity analysis. **No per-tumour progression rates exist to borrow.** |
| Maringe 2020 (PMC7417808) | 📖 | Reallocates patients between routes to diagnosis, each with its own English net survival. The "route" template. |
| Heiden 2021 (PMC8160592) | 📖 | Stage I NSCLC, 9,904 VA patients, 96 % men. Delay measured **from the diagnostic CT** to surgery; worse recurrence and survival beyond 12 weeks; **no association with upstaging**. |
| McPhail 2022 (PMC9046095) | 📖 | Emergency presentation: 12-month mortality OR ≥ 1.9 in all 112 jurisdiction–site strata; > 3.2 for all sites before adjusting for stage. Denmark and Norway included. |
| Neal 2015 (PMC4385982) | 📖 | Lung: as many positive as negative and null associations. Pancreas: 2 of 5 positive. Only 7 of 177 articles addressed the waiting-time paradox. |
| Tørring 2011 (PMC3065288) | 📖 | *Br J Cancer* 2011;104(6):934–40 (PMC3111212 is only its correction). Alarm symptoms: 3-year mortality lowest at about 5 weeks; OR 2.56 (1.29–5.05) for 0–4 vs 5–11 weeks. |
| Heinävaara 2016 (PMC4984912) | 📖 | HR 0.67 (0.49–0.90) for attenders after a self-selection correction of 1.56 from an earlier Finnish estimate. |
| Sarkeala 2008 (PMC2243161) | 📖 | Title: "Breast cancer mortality with varying invitational policies in organised mammography". |
| Khalife 2025 | 📖 | 42 clinicians, two workshops, MSD-funded, one MSD author; the authors call the differences "hypothetical". Waiting-time table and first-contact shares as quoted above; stage I share 17 % in Finland vs over 25 % in Denmark and Norway. |
| Crawford 2002 | ✓ | *BMJ* 2002;325:196 (PMC117451), not the *Br J Cancer*. |
| Lundberg 2020 | ✓ | Abstract only: flexible parametric relative-survival models. Finnish lung and pancreas figures still unread. |
| Falcaro 2015, Duffy 2002, Sanjeevi 2016, Vyas 2020 | ✓ | Paywalled. Read through a library if they go on a slide. |
| Danish standard pathway times | ✗ | sst.dk refused automated access. |

## A. Model structure

### A1. Relative survival with proportional excess hazards, and the scale of each HR

- **Frame:** `S(5) = S_0(5)^{∏ HR_k}` on the excess-hazard scale (Dickman et al. 2004 ○), where `S_0` is now the **Nordic** 5-year relative survival for the profile (A3).
- **Scales:** Zai's HRs are cancer-specific, a fair stand-in for excess hazard where cause of death is coded well (Sarfati et al. 2010 ✓). Hanna's and Heiden's are overall mortality, diluted towards 1 by other-cause deaths. The conversion `HR_excess ≈ 1 + (HR_overall − 1) / p`, with `p` the share of the hazard that is excess (from relative vs observed survival), follows from `h = h_exp + h_excess`.
- **Where it matters:** the conversion is small for lung and pancreas, where nearly all deaths within 5 years are excess deaths, and **largest for colorectal**, which is the first site built (5-year survival about 65 %). So the conversion is always applied, not a toggle, and `p` is loaded per site and sex.
- **Residual risk:** proportional hazards over 0–5 years is doubtful for stage and emergency presentation, whose effects concentrate in the first year (McPhail 2022 📖). Acceptable for a 5-year summary. Offer no 1-year output from the same parameters.

### A2. One parameter per arrow (no multiplied marginals)

- **The problem with the original:** education, route, delay, stage and screening sit on one causal chain. Multiplying HRs from models with different adjustment sets treats each coefficient as a total effect (the Table 2 fallacy, Westreich & Greenland 2013 ✓), and hazard ratios are non-collapsible (Hernán 2010 ✓). Zai's mortality HR is adjusted for stage and treatment, so it is the *direct* effect; Zai's stage OR is the path *through* stage. Multiplying both with a screening RR counts education twice and stage three times.
- **The structure, each arrow one parameter:**

  ```text
  site, sex, age band ──────────────> Nordic baseline S_0 (by stage where known)
  education ──(Zai OR)──> stage mix ──> S_0 by stage                      [skipped when stage is given]
  care route ──(route-specific stage mix, Maringe-style)──> stage mix     [skipped when stage is given]
  days from trigger to treatment beyond target ──(Hanna, Heiden)──> excess hazard
  days before the trigger beyond target ──(Sud per-day, toggle)──> excess hazard
  education ──(Zai direct HR)──> excess hazard                            [analyst view only]
  Finland residual (site, sex; toggle) ──> excess hazard
  ```

- **Rules:** when stage is given, the two arrows into the stage mix are skipped. The pre-trigger delay arrow is **never** skipped, because it is a direct effect, not a stage shift (B5). Use mediation language in the explanation: "direct", "through stage", "through waiting time" (VanderWeele 2015 ○).
- **Caveat on the direct effect:** Zai's HR conditions on stage and treatment, which are mediators. With unmeasured confounding between those mediators and survival, the "direct" effect is biased. One line on the model page.

### A3. Baseline: the Nordic level, not Finland

- **Original:** a Finnish baseline recalibrated over a synthetic population. **Problem:** NORDCAN's Finnish survival was observed under Finnish waiting times, so the synthetic population would have needed a Finnish distribution of days per step and of care routes, which we do not have. Without it, a patient with zero delay reproduces Finland and everyone else sits below, and "on target" shows no gain for an average Finn.
- **Now:** the baseline is the **Nordic level**, the strategy's own target: 5-year relative survival by site, sex and age band from Norway and Sweden (NORDCAN), and **by stage from Norway**, whose staging is complete. It was observed under near-target waiting times, so it *is* the on-target case. No recalibration, no synthetic population, no bisection.
- **The Finland residual:** an average Finnish profile with Finnish waits (the Yle medians, labelled preliminary) and the Finnish education mix, run through the model, lands above NORDCAN Finland. The gap that remains is a site- and sex-level factor on the excess hazard, stored on the version with its size. It is **a toggle, default on**, so that patient-level figures look Finnish; off shows what the profile would get if only timing and education differed.
- **Stage coding:** Finland records localised / regional / metastatic; Zai's OR is stage IV vs I–III; Norway publishes both TNM and summary stage. Use **Norway's summary stage (localised / regional / distant)** for the baseline, apply Zai's OR to the distant category, and record that the OR was estimated on a slightly different split.
- **Age bands:** NORDCAN's own; merge where counts are small and show the count. The 2020–2024 figures are period estimates; name them so.

## B. Time to treatment

### B4. The waiting-time paradox, Hanna's scope, and Heiden's clock

- **Hanna 📖:** delay from diagnosis to first curative treatment, or surgery to adjuvant treatment; seven cancers, **no pancreas or liver**; overall survival; 25 of 34 studies from the US. Lung surgery 1.06 (0.93–1.19) and NSCLC adjuvant chemotherapy 1.01 (0.99–1.04), both not significant. Colectomy 1.06 (1.01–1.12), colorectal adjuvant 1.13 (1.09–1.17). The high-validity rule required colon, lung and cervix studies to analyse the paradox; that reduces confounding by indication but does not remove it.
- **The paradox:** sicker patients are fast-tracked, so very short intervals go with worse survival (Crawford 2002 ✓; Tørring 2011 📖: lowest mortality at about 5 weeks, OR 2.56 for 0–4 vs 5–11 weeks). Neal 2015 📖: lung evidence mixed; pancreas 2 of 5 studies positive; only 7 of 177 articles addressed the paradox.
- **Hanna's limits:** log-linearity between 4 and 16 weeks of *total* delay; not for a minimal safe delay.
- **Heiden 📖 (stage I NSCLC):** worse recurrence and survival beyond 12 weeks **from the diagnostic CT**, no upstaging. The diagnostic CT is the moment the Nordic trigger fires. So Heiden's clock is the pathway clock: 12 weeks (84 days) from trigger to surgery, against a Nordic target of 42–44.
- **Recommendation:**
  - Apply delay effects on the **days from trigger to treatment start beyond the target**, on a curative route only. Cap the **total** post-trigger delay used in the formula at 16 weeks, with a warning beyond.
  - Colorectal: Hanna (colectomy; adjuvant). Lung: Heiden's step at 12 weeks from the trigger, with Hanna's non-significant 1.06 as the alternative. Pancreas: no estimate (Sanjeevi 2016 ✓ is about progression to unresectability, abstract only); graded `assumption` with a range.
  - Days at or under target have no effect: the model never claims a benefit from being faster than the standard, which keeps it out of the paradox region.
  - Wording: "survival associated with this waiting time under assumption X", never "you will lose Y".
- **Residual risk:** residual confounding by indication; US cohorts applied to Finland (C7).

### B5. Days before the trigger

- **Mechanism:** none of the modelling literature uses per-tumour stage progression. Maringe 2020 📖 moves patients between routes; Sud 2020 📖 applies a per-day fatality HR directly. Heiden 📖 found no upstaging with longer waits. There is no stage-shift parameter to borrow.
- **Lead time:** survival is counted from diagnosis, so an earlier diagnosis looks better even when death comes no later (Jensen 2017 📖).
- **Recommendation:** the days before the trigger are shown as **days behind target** (exact: Sweden's 11-day filter time, and the primary-care access figures). Their survival effect is **one toggle, off by default**: Sud's per-day fatality HR by survival class (0.0056 per day for lung, pancreas and colorectal), graded `assumption`, with a lead-time warning, ±8 % as its pseudo-SD. It is a direct effect and is never skipped.
- **Residual risk:** the weakest link, and it stays visible as a toggle rather than a hidden assumption.

### B6. Target times

- **Decision:** per site and step, the **median of the national standard times** of the countries that define the step: Norway and Sweden now (read), Denmark when loaded. Each country's value stays in the parameter table and is shown on the model page.
- **Mapping to the handout's eight steps**, through the Aarhus statement intervals (Weller et al. 2012 ✓):
  - steps 1–2 (symptoms → considering care → first contact): the patient interval; no target; shown as context;
  - step 3 (first contact → physician assessment): no standard time; Khalife's 2–7 days as a Nordic reference, graded `assumption`;
  - steps 4–5 (assessment → tests → diagnosis): Sweden's filter (6 days to imaging, 11 to the pathway decision), then Norway's 7 + 21 from referral to work-up complete;
  - steps 6–8 (diagnosis → MDT plan → treatment start): Norway's 14 (surgery, radiotherapy) or 7 (drugs); and the whole-pathway deadline, trigger → treatment, median of 42 and 44 = 43.
- **Residual risk:** the countries define sub-steps differently (Sweden counts from the decision on well-founded suspicion, Norway from the referral received). Use the whole-pathway deadline as the primary one and the sub-steps as guidance.

## C. Transportability

### C7. Where the effects come from, and the Finland residual

- **The delay effects are not Nordic.** Hanna is mostly US registries, Heiden is US veterans (96 % men), Sud is England. Only the targets and the baseline are Nordic; only the education effect is Finnish. Say so: "Nordic baseline, Finnish education gradient, international delay effects".
- **The Nordic convergence is a bundle.** Denmark's pathways came with cancer plans, centralisation and investment (Lundberg 2020 ✓; Arnold 2019 ✓). Norway and Sweden evaluated waiting times, not survival (Nilssen ✓). A difference-in-differences cannot separate the pathway from the bundle, and staggered adoption adds bias (Goodman-Bacon 2021 ○). **Dropped.**
- **What replaces it:** the Finland residual (A3). It is the honest measure of how much of the gap the modelled factors do *not* explain, and it is computed from data we have.
- **The transport dial** ("all of the effect applies in Finland" / "half") is gone as a separate toggle; the residual absorbs it. The limits of transport are stated on the model page (Degtiar & Rose 2023 ✓).

### C8. Stage

- Finland's stage is missing for 30 % of cases in Zai 📖 (2000–2019, all sites); the IHE dashboard's 61 % is for all cancers in 2019–2023, with 35 % for breast and 87 % for melanoma (the stage source in ADA, `op_39f97a91…`). Both are right; they count different years and definitions. Imputation (Falcaro 2015 ✓) needs individual data.
- **Now:** stage is an optional input. Given: Norway's stage-specific baseline. Not given: the stage mix for the profile (education and route), then the mixture. Coding per A3.

## D. Equity terms

### D9. Education, care route, and what is shown

- **Education has a real effect in Finland.** Zai 📖: stage IV OR 1.10 (men), 1.15 (women); less surgery (OR 0.91, 0.94; lung surgery for women 0.85); cancer-specific mortality HR 1.13, 1.14 after stage and treatment (lung, women 1.22). Pokhrel 📖: lung 5-year survival 18.8 vs 12.3 % for women with high vs basic education.
- **Mother tongue is out**, as an input and as a flag: the Finnish registry data does not record it (Zai has only "both parents born abroad", 1.9 %, as a covariate), so the model could neither estimate nor check it.
- **Care route:** emergency presentation is a marker of advanced disease as much as a cause (McPhail 📖); it enters through the stage mix. The public-route delay (DLBCL, Kuitunen, in ADA) enters through the days.
- **Ethics:** Vyas 2020 ✓ asks whether a group term relieves or worsens inequity; a lower prognosis labelled "because of your education" worsens it and is not actionable. Paulus & Kent 2020 ✓: if the ranking allocates a scarce resource (a navigator), fairness criteria apply.
- **Decision:** education stays in the model (for the residual and the population view) and in the analyst view; it is **never shown as lowering this patient's figure**. Per patient it produces flags: navigator support, and a check that every treatment option was discussed. Flags are worded as offers.

### D10. Screening

Dropped from the individual model: attenders self-select (Duffy 2002 ✓; Heinävaara 2016 📖 needed a 1.56 correction), and for a diagnosed patient screening has already acted through stage. It stays a population lever in the functions plan.

## E. Validation, intended use and communication

### E11. Validation without individual data

- **Verification:** unit tests against hand calculations; deadlines and days-behind are exact and tested as such.
- **The residual (an internal fit check, not a validation):** average Finnish profile with Finnish waits → compare with NORDCAN Finland per site and sex. The residual is then fitted to those same figures, so agreement afterwards validates nothing; it only shows how much the timing terms leave to the residual. A residual near zero would mean the timing terms, as estimated, account for the gap; a large one that they do not. External validation needs independent data (Finnish patient-level waits and outcomes), which is not available.
- **Education check (external):** the model's survival gap by education per site, against Pokhrel 2010's cause-specific survival by education. Pokhrel is not used as a parameter. (The Cancer Registry's *mortality* ratios by education were the earlier choice; they include incidence differences, which for lung dwarf the survival gradient, so they are the wrong quantity.)
- **Cross-model:** the delay-only effect against Hanna's worked examples (8 and 12 weeks of colectomy delay).
- **Not possible:** discrimination, calibration curves, individual external validation. Say so. The model is a decision-analytic model under ISPOR-SMDM practice (Eddy 2012 ○), not a TRIPOD prediction model; the model card still follows the TRIPOD+AI items that apply (Collins 2024 ✓).

### E12. Regulation and the data rule

- **MDR:** software that provides information for diagnostic or therapeutic decisions about an individual is a medical device, class IIa or higher under Rule 11 (MDCG 2019-11 Rev.1, June 2025 ✓). A deadline tracker built on published national standards is closer to a checklist than a prognostic device, but "which next step gains most" for one patient plausibly qualifies. The intended-purpose statement is what keeps the hackathon version out: *educational and planning use, synthetic profiles, not for decisions about the care of an individual patient.*
- **AI Act:** a fixed-parameter model with no learning arguably falls outside the AI-system definition (Commission guidelines 2025 ✓, "simple prediction systems"); if inside, Annex III 5(a) (○ check wording) could apply where a county uses it to prioritise patients. High-risk obligations are now expected from December 2027 ✓.
- **Data rule (decided):** ADA is not for patient data. A permanent red banner on every page says so. Evaluations therefore go through the in-platform agent like any other tool call; no per-tool privacy exception.

### E13. Communication

- Deadlines and days first; they are exact.
- Survival as **people out of 100**, in an icon array, rounded to whole people (Zipkin 2014 ○; PREDICT's display, Wishart 2010 ○). A numeric range does not harm trust (van der Bles 2019 ✓).
- **Two toggles, not a Monte Carlo:** "Finland residual" (default on) and "days before the trigger count" (default off). Each shows its own figure; the range across the four combinations is stated. Within a setting, the interval comes from the parameters' CIs directly.
- Every lever carries its evidence grade: `standard` (a national pathway time), `meta-analysis`, `cohort`, `registry`, `assumption`.
- No log-hazard waterfall for end users; it stays in the analyst view.

## Revised specification (v2)

- **Name:** patient pathway model.
- **Sites:** colorectal and lung (pancreas third, mostly `assumption`; liver not modelled).
- **Inputs:** site (suspected or confirmed), sex, age band, education, care route of first contact, stage if known, treatment intent if known (curative / palliative), the presentation (checkboxes for the suspicion and well-founded-suspicion criteria), and the dates or days per step.
- **Patient-level output, in this order:**
  1. **Trigger:** whether the presentation meets suspicion (imaging due) and well-founded suspicion (pathway starts), per country, with the criteria that fired.
  2. **Deadlines:** clock start; first specialist visit, work-up complete, treatment start, each with its target, status and the countries behind it; the next action.
  3. **Days behind target per step**, with the patient interval as context.
  4. **Survival, people out of 100:** as it stands vs on target, with the two toggles and the range; each lever graded.
  5. **Support to offer** (flags) and **read with care** (lead time, confounding by indication, where the effects come from, not validated on Finnish patients).
- **Population view:** Nordic level → timing-adjusted → Finland, per site and sex, with the residual named.
- **Modules (A2):** Nordic baseline by stage; stage mix from education and route (skipped when stage is given); post-trigger delay (Hanna, Heiden; 16-week total cap); pre-trigger delay (Sud, toggle); direct education (analyst only); Finland residual (toggle).
- **Validation (E11):** verification, the residual check, the Pokhrel education check, Hanna's worked examples.

## Reference list for the presentation

**National pathways (the trigger and the targets)**
- 📖 Helsedirektoratet. *Pakkeforløp for lungekreft*: Forløpstider; Kriterier for henvisning til pakkeforløp. Last revised 3 July 2026. https://www.helsedirektoratet.no/nasjonale-forlop/lungekreft
- 📖 Regionala cancercentrum i samverkan. *Standardiserat vårdförlopp lungcancer*, version 1.4, 2024-11-05, and the short version for primary care. https://kunskapsbanken.cancercentrum.se/globalassets/cancerdiagnoser/lunga-och-lungsack/vardforlopp/svf-lungcancer.pdf
- ○ Sundhedsstyrelsen. *Pakkeforløb for lungekræft*, section "Forløbstider". https://sst.dk (download by hand)
- ✓ Weller D, Vedsted P, Rubin G et al. The Aarhus statement. *Br J Cancer* 2012;106:1262–7. doi:10.1038/bjc.2012.68

**The problem (Finland vs the Nordic countries)**
- ✓ Lundberg FE et al. Trends in cancer survival in the Nordic countries 1990–2016: the NORDCAN survival studies. *Acta Oncol* 2020;59(11):1266–74. doi:10.1080/0284186X.2020.1822544
- ✓ Arnold M et al. Progress in cancer survival, mortality, and incidence in seven high-income countries 1995–2014 (ICBP SURVMARK-2). *Lancet Oncol* 2019;20(11):1493–505.
- 📖 Khalife et al. Comparative study of lung cancer care and survival outcomes across the Nordic countries. *Acta Oncol* 2025;64:734–41. (42 clinicians; MSD-funded.)
- ✓ Yle MOT (2025). Lung cancer, symptoms to treatment: 155 days in Finland, 107 in Sweden, 67 in Denmark (unpublished study, Kuittinen, University of Eastern Finland). https://yle.fi/a/74-20251023

**Pathways and survival**
- 📖 Jensen H, Tørring ML, Vedsted P. Prognostic consequences of implementing cancer patient pathways in Denmark. *BMC Cancer* 2017;17:627. PMC5585953
- ✓ Nilssen Y et al. Norwegian cancer patient pathways: inclusion, compliance and waiting times. *BMC Cancer* 2020 and 2022. ○ Check the titles.

**Time to treatment**
- 📖 Hanna TP et al. Mortality due to cancer treatment delay: systematic review and meta-analysis. *BMJ* 2020;371:m4087. PMC7610021
- 📖 Heiden BT et al. Analysis of delayed surgical treatment and oncologic outcomes in clinical stage I non-small cell lung cancer. *JAMA Netw Open* 2021. PMC8160592
- 📖 Neal RD et al. Is increased time to diagnosis and treatment in symptomatic cancer associated with poorer outcomes? Systematic review. *Br J Cancer* 2015;112(Suppl 1):S92–107. PMC4385982
- 📖 Tørring ML et al. Time to diagnosis and mortality in colorectal cancer: a cohort study in primary care. *Br J Cancer* 2011;104(6):934–40. PMC3065288
- ✓ Crawford SC et al. The waiting time paradox. *BMJ* 2002;325:196. PMC117451
- ✓ Sanjeevi S et al. Impact of delay between imaging and treatment in patients with potentially curable pancreatic cancer. *Br J Surg* 2016.
- 📖 Sud A et al. Collateral damage: the impact on outcomes from cancer surgery of the COVID-19 pandemic. *Ann Oncol* 2020;31(8):1065–74. PMC7237184
- 📖 Maringe C et al. The impact of the COVID-19 pandemic on cancer deaths due to delays in diagnosis in England. *Lancet Oncol* 2020;21(8):1023–34. PMC7417808
- 📖 McPhail S et al. Emergency presentation (ICBP). *Lancet Oncol* 2022;23(5):587–600. PMC9046095

**Inequity in Finland**
- 📖 Zai et al. Disparities in cancer incidence, stage at diagnosis, treatment and mortality across socioeconomic groups in Finland. *BMJ Public Health* 2025. PMC12551501
- 📖 Pokhrel A et al. Education, survival and avoidable deaths in cancer patients in Finland. *Br J Cancer* 2010;103:1109–14. PMC2965870

**Methods**
- ○ Dickman PW et al. Regression models for relative survival. *Stat Med* 2004;23:51–64.
- ✓ Sarfati D, Blakely T, Pearce N. Measuring cancer survival in populations. *Int J Epidemiol* 2010;39(2):598–610.
- ✓ Westreich D, Greenland S. The Table 2 fallacy. *Am J Epidemiol* 2013;177(4):292–8.
- ✓ Hernán MA. The hazards of hazard ratios. *Epidemiology* 2010;21(1):13–15.
- ○ VanderWeele TJ. *Explanation in Causal Inference*. OUP, 2015.
- ✓ Degtiar I, Rose S. A review of generalizability and transportability. *Annu Rev Stat Appl* 2023;10:501–24.
- ✓ Falcaro M et al. Estimating excess hazard ratios and net survival when covariate data are missing. *Epidemiology* 2015;26:421–8.
- ○ Goodman-Bacon A. Difference-in-differences with variation in treatment timing. *J Econometrics* 2021;225:254–77.

**Screening**
- ✓ Duffy SW et al. Correcting for non-compliance bias in case–control studies to evaluate cancer screening programmes. *J R Stat Soc C* 2002;51:235–43.
- 📖 Sarkeala T et al. *Br J Cancer* 2008;98:641–5. PMC2243161
- 📖 Heinävaara S et al. *Br J Cancer* 2016;114:1038–44. PMC4984912

**Validation, ethics, communication, regulation**
- ✓ Collins GS et al. TRIPOD+AI statement. *BMJ* 2024;385:e078378.
- ✓ Van Calster B et al. Calibration: the Achilles heel of predictive analytics. *BMC Med* 2019;17:230.
- ○ Eddy DM et al. ISPOR-SMDM Task Force-7: model transparency and validation. *Med Decis Making* 2012;32:733–43.
- ✓ Vyas DA, Eisenstein LG, Jones DS. Hidden in plain sight. *N Engl J Med* 2020;383:874–82.
- ✓ Paulus JK, Kent DM. Predictably unequal. *npj Digit Med* 2020;3:99.
- ✓ van der Bles AM et al. Communicating uncertainty about facts, numbers and science. *R Soc Open Sci* 2019;6:181870.
- ○ Zipkin DA et al. Evidence-based risk communication. *Ann Intern Med* 2014;161:270–80.
- ○ Wishart GC et al. PREDICT. *Breast Cancer Res* 2010;12:R1.
- ✓ Regulation (EU) 2017/745 (MDR), Annex VIII Rule 11; MDCG 2019-11 Rev.1 (June 2025).
- ✓ Regulation (EU) 2024/1689 (AI Act), Art. 3(1), Art. 6, Annex III; Commission guidelines on the definition of an AI system (2025).
