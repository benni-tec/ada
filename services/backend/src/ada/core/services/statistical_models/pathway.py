"""The patient pathway model, v1: lung cancer. Every figure carries the passage it was
checked against on 2026-11-14 (docs/superpowers/plans/2026-11-14-statistical-models-
grounding.md, "Full-text check"). Colorectal and pancreas follow when their criteria,
standard times and baseline are loaded as sources."""

from ada.core.models.statistical_models import (
    BaselineCell,
    Citation,
    ComparisonPopulation,
    Criterion,
    EvidenceGrade,
    Flag,
    Form,
    Modality,
    ModelSpec,
    Parameter,
    PathwayStep,
    Scale,
    TargetTime,
    Term,
    Toggle,
    TriggerStage,
)

NAME = "Patient pathway model"
DESCRIPTION = (
    "Whether a presentation would start a Nordic fast-track lung-cancer pathway, when each "
    "step is due, how many days the pathway is behind target, and, second and graded, the "
    "5-year survival associated with the difference. Nordic baseline, Finnish education "
    "gradient, international delay effects."
)
KIND = "patient_pathway"

NORWAY = Citation(
    source="Helsedirektoratet, Pakkeforløp for lungekreft (last revised 3 July 2026)",
    passage="Fra henvisning mottatt til første fremmøte utredende avdeling: 7 kalenderdager; til "
    "avsluttet utredning: 21; til start behandling: kirurgisk 14, medikamentell 7, "
    "strålebehandling 14; fra henvisning mottatt til start behandling: 42 / 35 / 42.",
    grade=EvidenceGrade.STANDARD,
    url="https://www.helsedirektoratet.no/nasjonale-forlop/lungekreft/forlopstider-i-pakkeforlop-for-lungekreft",
    country="Norway",
)
NORWAY_CRITERIA = NORWAY.model_copy(
    update={
        "passage": "Begrunnet mistanke om lungekreft utløses av at enten radiologi viser "
        "malignitetssuspekt forandring i lunge, eller en biopsi tatt fra annet organ viser "
        "kreft som tyder på origo i lunge.",
        "url": "https://www.helsedirektoratet.no/nasjonale-forlop/lungekreft/inngang-til-pakkeforlop-for-lungekreft/begrunnet-mistanke-kriterier-for-henvisning-til-pakkeforlop",
    }
)
SWEDEN = Citation(
    source="Regionala cancercentrum, Standardiserat vårdförlopp lungcancer, version 1.4 "
    "(2024-11-05)",
    passage="Ledtider för nationell uppföljning: beslut välgrundad misstanke till start av första "
    "behandling, läkemedel 40 kalenderdagar; kirurgi eller strålbehandling 44; palliativ 30. "
    "Primärvård: remissbeslut 1, till lungröntgen/DT 5, svar 1, beslut om välgrundad misstanke "
    "3, remiss mottagen 1.",
    grade=EvidenceGrade.STANDARD,
    url="https://kunskapsbanken.cancercentrum.se/globalassets/cancerdiagnoser/lunga-och-lungsack/vardforlopp/svf-lungcancer.pdf",
    country="Sweden",
)
SWEDEN_SUSPICION = SWEDEN.model_copy(
    update={
        "passage": "Följande ska föranleda misstanke: nytillkomna luftvägssymtom (t.ex. hosta "
        "eller andnöd) med en varaktighet av 6 veckor hos rökare eller före detta rökare över "
        "40 år; bröst- eller skuldersmärta utan annan förklaring; blodig hosta.",
    }
)
SWEDEN_WELL_FOUNDED = SWEDEN.model_copy(
    update={
        "passage": "Välgrundad misstanke föreligger vid: fynd vid bilddiagnostik som ger misstanke "
        "om lungcancer; metastasfynd som ger misstanke om lungcancer; upprepad blodig hosta "
        "utan annan uppenbar orsak, även vid normal röntgen; obstruktion av vena cava "
        "superior; recurrenspares.",
    }
)
KHALIFE = Citation(
    source="Khalife et al., Acta Oncol 2025;64:734–41 (a survey of 42 clinicians; MSD-funded)",
    passage="Table 2: appointment at health centre for lung cancer symptoms, Finland 14 days; "
    "Sweden, Denmark, Norway, Iceland 2–7 days.",
    grade=EvidenceGrade.ASSUMPTION,
    url="https://medicaljournalssweden.se/actaoncologica/article/download/42778/50476",
)
HANNA = Citation(
    source="Hanna et al., BMJ 2020;371:m4087 (PMC7610021)",
    passage="The results for lung surgery were consistent with other sites, though not "
    "statistically significant (1.06, 0.93 to 1.19). Delay was measured from diagnosis to "
    "first treatment; the outcome is overall survival; log-linearity holds between four and 16 "
    "weeks.",
    grade=EvidenceGrade.META_ANALYSIS,
    url="https://doi.org/10.1136/bmj.m4087",
)
HEIDEN = Citation(
    source="Heiden et al., JAMA Netw Open 2021 (PMC8160592; VA, 9,904 patients, 96 % men)",
    passage="Surgical procedures delayed more than 12 weeks from the diagnostic CT were associated "
    "with increased risk of recurrence and worse overall survival: HR 1.132 (95% CI "
    "0.943–1.359). Time to surgery was not associated with pathologic upstaging.",
    grade=EvidenceGrade.COHORT,
    url="https://pmc.ncbi.nlm.nih.gov/articles/PMC8160592/",
)
SUD = Citation(
    source="Sud et al., Ann Oncol 2020;31:1065–74 (PMC7237184)",
    passage="Per-day hazard ratio for fatality: low progressiveness 0.0030, moderate and high "
    "0.0056 (no data for high; the moderate value applied). Varied by ±8 % in sensitivity "
    "analysis. Derived from surgical delay studies; applied here before the trigger as an "
    "assumption.",
    grade=EvidenceGrade.ASSUMPTION,
    url="https://pmc.ncbi.nlm.nih.gov/articles/PMC7237184/",
)
ZAI = Citation(
    source="Zai et al., BMJ Public Health 2025 (PMC12551501; 469,522 cases, 2000–2019)",
    passage="Stage IV vs I–III, low vs high education: men OR 1.10 (1.08–1.12), women 1.15 "
    "(1.13–1.17). Cancer-specific mortality, adjusted for age, year, stage, treatment, birth "
    "year, marital status, origin, region and urbanisation: men HR 1.13 (1.10–1.16), women "
    "1.14 (1.11–1.17); lung, women 1.22 (1.12–1.33). Surgery: lung, women OR 0.85 (0.78–0.93).",
    grade=EvidenceGrade.REGISTRY,
    url="https://pmc.ncbi.nlm.nih.gov/articles/PMC12551501/",
)
NORDCAN = Citation(
    source="NORDCAN 9.6, 5-year relative survival, lung cancer, 2020–2024, as quoted in the plan "
    "(docs/superpowers/plans/2026-11-14-statistical-models.md, Part 1)",
    passage="Lung: 17.9 % men / 30.8 % women in Finland, against 28–31 / 37–39 % elsewhere. The "
    "Nordic level is the mean of Sweden and Norway (National Cancer Strategy); the midpoints "
    "of the quoted ranges stand in until the per-country tables are loaded.",
    grade=EvidenceGrade.REGISTRY,
    url="https://nordcan.iarc.fr/",
)
YLE = Citation(
    source="Yle MOT (2025), reporting an unpublished study by Kuittinen, University of Eastern "
    "Finland",
    passage="Finland, lung cancer, symptom onset to treatment: about 155 days, of which more than "
    "50 the patient, 41 primary healthcare and 58 specialised healthcare; Sweden 107 days, "
    "Denmark 67. Preliminary. The split of the 41 and 58 days across steps is the model "
    "author's, in proportion to the targets.",
    grade=EvidenceGrade.ASSUMPTION,
    url="https://yle.fi/a/74-20251023",
)

LUNG = "lung"
FEMALE, MALE = "female", "male"


def _criterion(
    id: str, stage: TriggerStage, text: str, countries: tuple[str, ...], provenance: Citation
) -> Criterion:
    return Criterion(
        id=id, site=LUNG, stage=stage, text=text, countries=countries, provenance=provenance
    )


def pathway_spec() -> ModelSpec:
    return ModelSpec(
        outcome="5-year relative survival",
        sites=(LUNG,),
        terms=(
            Term(name="sex", levels=(FEMALE, MALE), reference=FEMALE),
            Term(
                name="age_band", levels=("under_60", "60_69", "70_79", "80_plus"), reference="60_69"
            ),
            Term(
                name="education",
                levels=("basic", "secondary", "tertiary"),
                reference="tertiary",
                display="analyst",
            ),
            Term(
                name="route",
                levels=("public_health_centre", "occupational", "private", "emergency"),
                reference="public_health_centre",
            ),
            Term(name="stage", levels=("localised", "regional", "distant"), reference="localised"),
        ),
        criteria=(
            _criterion(
                "lung_symptoms_smoker",
                TriggerStage.SUSPICION,
                "New airway symptoms (cough, breathlessness) for 6 weeks in a smoker or ex-smoker "
                "over 40",
                ("Sweden",),
                SWEDEN_SUSPICION,
            ),
            _criterion(
                "lung_chest_pain",
                TriggerStage.SUSPICION,
                "Chest or shoulder pain without another explanation",
                ("Sweden",),
                SWEDEN_SUSPICION,
            ),
            _criterion(
                "lung_haemoptysis",
                TriggerStage.SUSPICION,
                "Coughing blood",
                ("Sweden",),
                SWEDEN_SUSPICION,
            ),
            _criterion(
                "lung_imaging",
                TriggerStage.WELL_FOUNDED,
                "Imaging finding suggesting lung cancer",
                ("Norway", "Sweden"),
                SWEDEN_WELL_FOUNDED,
            ),
            _criterion(
                "lung_metastasis",
                TriggerStage.WELL_FOUNDED,
                "A metastasis or a biopsy from another organ suggesting lung cancer",
                ("Norway", "Sweden"),
                NORWAY_CRITERIA,
            ),
            _criterion(
                "lung_repeated_haemoptysis",
                TriggerStage.WELL_FOUNDED,
                "Repeated haemoptysis without another obvious cause, even with a normal X-ray",
                ("Sweden",),
                SWEDEN_WELL_FOUNDED,
            ),
            _criterion(
                "lung_svc",
                TriggerStage.WELL_FOUNDED,
                "Superior vena cava obstruction",
                ("Sweden",),
                SWEDEN_WELL_FOUNDED,
            ),
            _criterion(
                "lung_recurrent_nerve",
                TriggerStage.WELL_FOUNDED,
                "Recurrent laryngeal nerve palsy",
                ("Sweden",),
                SWEDEN_WELL_FOUNDED,
            ),
        ),
        targets=(
            TargetTime(
                site=LUNG,
                step=PathwayStep.CONTACT_TO_PHYSICIAN,
                days_by_country={"Nordic reference": 7},
                provenance=KHALIFE,
            ),
            TargetTime(
                site=LUNG,
                step=PathwayStep.PHYSICIAN_TO_IMAGING,
                days_by_country={"Sweden": 6},
                provenance=SWEDEN,
            ),
            TargetTime(
                site=LUNG,
                step=PathwayStep.IMAGING_TO_REFERRAL,
                days_by_country={"Sweden": 4},
                provenance=SWEDEN,
            ),
            TargetTime(
                site=LUNG,
                step=PathwayStep.REFERRAL_TO_SPECIALIST,
                days_by_country={"Norway": 7},
                provenance=NORWAY,
            ),
            TargetTime(
                site=LUNG,
                step=PathwayStep.SPECIALIST_TO_WORKUP,
                days_by_country={"Norway": 21},
                provenance=NORWAY,
            ),
            TargetTime(
                site=LUNG,
                step=PathwayStep.WORKUP_TO_TREATMENT,
                modality=Modality.SURGERY,
                days_by_country={"Norway": 14},
                provenance=NORWAY,
            ),
            TargetTime(
                site=LUNG,
                step=PathwayStep.WORKUP_TO_TREATMENT,
                modality=Modality.RADIOTHERAPY,
                days_by_country={"Norway": 14},
                provenance=NORWAY,
            ),
            TargetTime(
                site=LUNG,
                step=PathwayStep.WORKUP_TO_TREATMENT,
                modality=Modality.DRUGS,
                days_by_country={"Norway": 7},
                provenance=NORWAY,
            ),
            TargetTime(
                site=LUNG,
                step=None,
                modality=Modality.SURGERY,
                days_by_country={"Norway": 42, "Sweden": 44},
                provenance=NORWAY,
            ),
            TargetTime(
                site=LUNG,
                step=None,
                modality=Modality.RADIOTHERAPY,
                days_by_country={"Norway": 42, "Sweden": 44},
                provenance=NORWAY,
            ),
            TargetTime(
                site=LUNG,
                step=None,
                modality=Modality.DRUGS,
                days_by_country={"Norway": 35, "Sweden": 40},
                provenance=NORWAY,
            ),
        ),
        baseline=(
            BaselineCell(site=LUNG, sex=MALE, survival=0.295, provenance=NORDCAN),
            BaselineCell(site=LUNG, sex=FEMALE, survival=0.38, provenance=NORDCAN),
        ),
        parameters={
            "heiden_lung_surgery": Parameter(
                name="heiden_lung_surgery",
                estimate=1.132,
                ci_low=0.943,
                ci_high=1.359,
                scale=Scale.OVERALL,
                form=Form.BEYOND_12_WEEKS,
                provenance=HEIDEN,
            ),
            "hanna_lung_surgery": Parameter(
                name="hanna_lung_surgery",
                estimate=1.06,
                ci_low=0.93,
                ci_high=1.19,
                scale=Scale.OVERALL,
                form=Form.PER_4_WEEKS,
                provenance=HANNA,
            ),
            "sud_per_day": Parameter(
                name="sud_per_day",
                estimate=0.0056,
                ci_low=0.0056 * 0.92,
                ci_high=0.0056 * 1.08,
                scale=Scale.OVERALL,
                form=Form.PER_DAY,
                provenance=SUD,
            ),
            "zai_stage_or_men": Parameter(
                name="zai_stage_or_men",
                estimate=1.10,
                ci_low=1.08,
                ci_high=1.12,
                scale=Scale.ODDS_RATIO,
                form=Form.ODDS_RATIO,
                provenance=ZAI,
            ),
            "zai_stage_or_women": Parameter(
                name="zai_stage_or_women",
                estimate=1.15,
                ci_low=1.13,
                ci_high=1.17,
                scale=Scale.ODDS_RATIO,
                form=Form.ODDS_RATIO,
                provenance=ZAI,
            ),
            "zai_direct_men": Parameter(
                name="zai_direct_men",
                estimate=1.13,
                ci_low=1.10,
                ci_high=1.16,
                scale=Scale.CAUSE_SPECIFIC,
                form=Form.HAZARD_RATIO,
                provenance=ZAI,
            ),
            "zai_direct_lung_women": Parameter(
                name="zai_direct_lung_women",
                estimate=1.22,
                ci_low=1.12,
                ci_high=1.33,
                scale=Scale.CAUSE_SPECIFIC,
                form=Form.HAZARD_RATIO,
                provenance=ZAI,
            ),
        },
        arrows={
            "delay_post:lung:surgery": "heiden_lung_surgery",
            "delay_post:lung": "hanna_lung_surgery",
            "delay_pre": "sud_per_day",
            "stage_education:lung:male": "zai_stage_or_men",
            "stage_education:lung:female": "zai_stage_or_women",
            "direct_education:lung:male": "zai_direct_men",
            "direct_education:lung:female": "zai_direct_lung_women",
        },
        comparison=ComparisonPopulation(
            country="Finland",
            survival={f"{LUNG}:{MALE}": 0.179, f"{LUNG}:{FEMALE}": 0.308},
            days={
                LUNG: {
                    PathwayStep.SYMPTOMS_TO_CONTACT: 52,
                    PathwayStep.CONTACT_TO_PHYSICIAN: 14,
                    PathwayStep.PHYSICIAN_TO_IMAGING: 27,
                    PathwayStep.IMAGING_TO_REFERRAL: 5,
                    PathwayStep.REFERRAL_TO_SPECIALIST: 9,
                    PathwayStep.SPECIALIST_TO_WORKUP: 26,
                    PathwayStep.WORKUP_TO_TREATMENT: 18,
                }
            },
            provenance=YLE,
        ),
        toggles=(
            Toggle(
                name="finland_residual",
                label="Finland residual",
                default=True,
                about="The part of the Finnish shortfall that the days do not explain, as one "
                "factor per site and sex. On: the figures match Finnish survival. Off: what "
                "the profile would get if only the waiting times differed from the Nordic "
                "level.",
            ),
            Toggle(
                name="pre_trigger",
                label="Days before the trigger count",
                default=False,
                about="Sud's per-day rate on the days lost before imaging. An assumption: part of "
                "it is lead time.",
            ),
        ),
        flags=(
            Flag(
                term="education",
                level="basic",
                action="Offer a patient navigator to keep the next steps on time.",
                provenance=ZAI,
            ),
            Flag(
                term="education",
                level="basic",
                action="Check that every treatment option was discussed: less surgery is offered "
                "after basic education (Zai 2025, lung surgery for women OR 0.85).",
                provenance=ZAI,
            ),
            Flag(
                term="route",
                level="public_health_centre",
                action="Direct imaging referral from the health centre shortens the time to the "
                "trigger (a system lever).",
                provenance=KHALIFE,
            ),
        ),
        intended_use=(
            "An educational and planning tool that shows how a lung-cancer pathway compares with "
            "the "
            "Nordic fast-track standards, using synthetic example profiles. Not for decisions "
            "about "
            "the care of an individual patient."
        ),
        cautions=(
            "Survival is counted from diagnosis, so an earlier diagnosis looks better even if "
            "death comes no later (lead time).",
            "Sicker patients are often treated faster, which hides part of the effect of waiting "
            "(confounding by indication).",
            "Nordic baseline, Finnish education gradient, American and English delay effects; not "
            "validated on Finnish patients.",
        ),
    )
