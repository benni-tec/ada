# Patient pathway model: demo profiles and slide outline

> Synthetic profiles for the demo, and the outline of the presentation. Every profile is
> invented; none describes a person. The platform's banner says so on every page.

## Three synthetic profiles

Each is an `EvaluationInputs` object. For REST, wrap it: `POST /api/models/{id}/evaluate`
with `{"inputs": {…}, "version": 1}` (version optional, the latest when left out). For the
`evaluate_model` tool, pass it as the `inputs` argument with `model_id` and `session_id`. As a
case, the same values plus `county` are the body `{"values": {…}}` of
`PUT /api/case-types/{id}/cases/{key}`. Days are days spent in each step so far; a step left
out has not started.

### 1. Past the deadline, plan not booked

A woman of 64, smoker, basic education, first contact at a public health centre with a
nurse. Cough for eight weeks at first contact (Sweden's suspicion criteria), seen by a
physician two weeks later, chest X-ray two weeks after that showing a suspicious lesion
(the trigger). Work-up complete; twelve days waiting for the treatment plan.

```json
{"site": "lung", "sex": "female", "age_band": "60-69", "education": "basic",
 "route": "public_health_centre", "intent": "curative", "modality": "surgery",
 "presentation": ["lung_symptoms_smoker", "lung_imaging"],
 "days": {"symptoms_to_contact": 51, "contact_to_physician": 14, "physician_to_imaging": 13,
          "imaging_to_referral": 1, "referral_to_specialist": 8, "specialist_to_workup": 26,
          "workup_to_treatment": 12}}
```

What the page shows: the pathway would have started in Denmark, Norway and Sweden on day
27; treatment start was due on day 71 and today is day 74 (overdue by three days); 20 days
behind target so far, most of them before the X-ray. Survival second: 5-year relative survival 35 per 100 as it
stands and on target (the remaining wait is under Heiden's twelve weeks), 32–39 across the
settings. Support: a navigator, and a
check that every treatment option was discussed.

### 2. On time after the trigger, slow before it

A man of 72, ex-smoker, tertiary education, occupational health. Chest pain for a month,
imaging ordered at the first visit but done three weeks later. From the X-ray on, every
step inside target. Shows that the days are lost before the trigger, where no national
standard reaches, and that the model gives no survival penalty for the post-trigger
pathway.

```json
{"site": "lung", "sex": "male", "age_band": "70-79", "education": "tertiary",
 "route": "occupational", "intent": "curative", "modality": "surgery",
 "presentation": ["lung_chest_pain", "lung_imaging"],
 "days": {"symptoms_to_contact": 30, "contact_to_physician": 2, "physician_to_imaging": 22,
          "imaging_to_referral": 2, "referral_to_specialist": 5, "specialist_to_workup": 18,
          "workup_to_treatment": 3}}
```

### 3. Pancreas, palliative intent

A woman of 81, emergency presentation with jaundice and an imaging finding, stage
distant, palliative intent. Shows the model switching the delay effects off (they were estimated
for curative treatment), the deadlines still shown (the drug-treatment target stands in for Sweden's
22-day palliative time, which is not a step of the model), and the baseline taken from
Norway's survival for distant pancreatic cancer (Cancer in Norway 2025), since the stage is
known.

```json
{"site": "pancreas", "sex": "female", "age_band": "80-89", "education": "secondary",
 "route": "emergency", "stage": "distant", "intent": "palliative", "modality": "drugs",
 "presentation": ["panc_jaundice", "panc_imaging"],
 "days": {"symptoms_to_contact": 10, "contact_to_physician": 0, "physician_to_imaging": 1,
          "imaging_to_referral": 1, "referral_to_specialist": 4}}
```

## Slides

Published as a page at https://claude.ai/artifact/4LSDyw28ehwNQKTyhSsKNy (private until shared); the
source is `2026-11-14-pathway-model-slides.html` beside this file. The outline:

1. **The gap.** Lung cancer, 5-year survival: Finland 18 % (men), the Nordic level 31 %
   (NORDCAN 2020-2024, from ADA's operator). Lundberg 2020; NORDCAN.
2. **Where the days go.** 155 days from symptoms to treatment in Finland, 107 in Sweden,
   67 in Denmark; in Finland more than 50 the patient, 41 primary care, 58 specialised
   care (Yle MOT 2025, unpublished). Only 40–60 % see a doctor at first contact, 14 days
   to an appointment (Khalife 2025, a survey).
3. **What Denmark, Norway and Sweden have that Finland does not.** A trigger:
   "well-founded suspicion", an imaging finding or a metastasis. A clock: 6–7 days to the
   first visit, 28–30 to the end of work-up, 42–45 to treatment. Finland: no national
   trigger, no standard times, no cancer-specific waiting-time statistics.
   (Helsedirektoratet; RCC; Sundhedsstyrelsen.)
4. **Does it matter?** After Denmark's pathways, lung 3-year survival among symptomatic
   primary-care patients 11 → 20 %, adjusted for stage (Jensen 2017); with the lead-time
   caveat the authors give themselves.
5. **The tool at the point of care.** Live demo, profile 1: the trigger fires, the
   deadlines show, treatment start overdue by three days. The exact part: no hazard ratio needed.
6. **Then survival, second and graded.** 5-year relative survival 35 per 100, 32–39 across
   two settings; every lever
   names its evidence (national standard, meta-analysis, one cohort, assumption).
7. **How it is built.** One parameter per arrow, so nothing counts twice (Westreich &
   Greenland 2013); Nordic baseline, Finnish education gradient (Zai 2025), international
   delay effects (Hanna 2020, Heiden 2021, Sud 2020); every figure with its passage.
8. **What timing explains.** Population tab: Nordic 31 → with Finland's waits 28 →
   Finland 18. Timing explains 3 of 13 points at the published rate; the rest is
   treatment access, stage at diagnosis, smoking, registry practice. The residual is shown,
   not hidden.
9. **Education.** The gap survives adjustment for stage and treatment (Zai HR 1.13–1.14;
   Pokhrel: lung, women 18.8 vs 12.3 %). The model carries it and never shows it as a
   lower figure: it becomes a navigator and a check that options were offered.
10. **What it is not.** Lead time, the waiting-time paradox, no Finnish patient-level
    validation. Educational use, synthetic profiles, a banner on every page. A clinical
    version would be a medical device (MDR Rule 11) and need Findata.
11. **Next.** Finland's days per step for colorectal and pancreas; Sweden's and Denmark's
    survival by stage beside Norway's; the fast-track times Finland would need.
