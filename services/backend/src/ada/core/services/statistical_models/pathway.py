"""The patient pathway model, v1: lung, colorectal and pancreatic cancer. Every figure
carries the passage it was checked against on 2026-11-14 (docs/superpowers/plans/
2026-11-14-statistical-models-grounding.md, "Full-text check"). The baseline comes from
the NORDCAN survival operator in the "Nordic cancer care" project, cited by operator and
run."""

import math

from ada.core.models.statistical_models import (
    NO_PATHWAY,
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
    "Whether a presentation would start a Nordic fast-track pathway for lung, colorectal or "
    "pancreatic cancer, when each "
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
    source_id="01a1dc00-f89d-724d-9207-d11e5b1f70bd",
    country="Norway",
)
NORWAY_CRITERIA = NORWAY.model_copy(
    update={
        "passage": "Begrunnet mistanke om lungekreft utløses av at enten radiologi viser "
        "malignitetssuspekt forandring i lunge, eller en biopsi tatt fra annet organ viser "
        "kreft som tyder på origo i lunge.",
        "url": "https://www.helsedirektoratet.no/nasjonale-forlop/lungekreft/inngang-til-pakkeforlop-for-lungekreft/begrunnet-mistanke-kriterier-for-henvisning-til-pakkeforlop",
        "source_id": "01a1dc00-f91b-748a-8e15-006a70828e14",
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
    source_id="01a1db1c-e73f-75a4-b294-20172adf3bc0",
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
    url="https://medicaljournalssweden.se/actaoncologica/article/view/42778",
    source_id="01a1dc01-a016-7643-8c5d-87f8f76a46c9",
)
# The effect of having no standardised cancer pathway on the diagnostic interval: Denmark
# before (2004/05) and after (2010) its cancer patient pathways. Finland has none, so its
# expected days per diagnostic step are the Nordic standard times before / after.
JENSEN = Citation(
    source="Jensen et al., BMC Cancer 2015;15:308 (PMC4412104; Denmark, three cohorts)",
    passage="The median DI was statistically significantly lower across time: 49 "
    "(interquartile interval (IQI): 24;96) days before, 35 (IQI: 16;78) days during and 32 "
    "(IQI: 14;73) days after CPP implementation. The median diagnostic interval was 14 (95% "
    "CI: 11;16) days shorter during and 17 (95% CI: 15;19) days shorter after the "
    "implementation of CPPs than before.",
    grade=EvidenceGrade.COHORT,
    url="https://doi.org/10.1186/s12885-015-1317-7",
    country="Denmark",
)
# 49 days before over 32 after; the interval from the 17 (15 to 19) days the after cohort
# was shorter: 49 / 34 to 49 / 30.
NO_PATHWAY_RATIO = (round(49 / 32, 3), round(49 / 34, 3), round(49 / 30, 3))

HANNA = Citation(
    source="Hanna et al., BMJ 2020;371:m4087 (PMC7610021)",
    passage="The results for lung surgery were consistent with other sites, though not "
    "statistically significant (1.06, 0.93 to 1.19). Delay was measured from diagnosis to "
    "first treatment; the outcome is overall survival; log-linearity holds between four and 16 "
    "weeks.",
    grade=EvidenceGrade.META_ANALYSIS,
    url="https://doi.org/10.1136/bmj.m4087",
    source_id="01a1dc00-fa74-75ef-9bff-68dba0cb64dd",
)
HEIDEN = Citation(
    source="Heiden et al., JAMA Netw Open 2021 (PMC8160592; VA, 9,904 patients, 96 % men)",
    passage="Patients who underwent surgical treatment within 12 weeks of diagnosis had "
    "significantly better overall survival than those with procedures delayed more than 12 "
    "weeks (HR, 1.132; 95% CI, 1.064-1.204). Time to surgery was not associated with "
    "pathologic upstaging.",
    grade=EvidenceGrade.COHORT,
    url="https://pmc.ncbi.nlm.nih.gov/articles/PMC8160592/",
    source_id="01a1dc00-fac4-764b-8f42-fea3a16e7a5f",
)
SUD = Citation(
    source="Sud et al., Ann Oncol 2020;31:1065–74 (PMC7237184)",
    passage="Per-day hazard ratio for fatality: low progressiveness 0.0030, moderate and high "
    "0.0056 (no data for high; the moderate value applied). Varied by ±8 % in sensitivity "
    "analysis. Derived from surgical delay studies; applied here before the trigger as an "
    "assumption.",
    grade=EvidenceGrade.ASSUMPTION,
    url="https://pmc.ncbi.nlm.nih.gov/articles/PMC7237184/",
    source_id="01a1dc00-fb0e-77d1-8503-16d5c3166c22",
)
ZAI = Citation(
    source="Zai et al., BMJ Public Health 2025 (PMC12551501; 469,522 cases, 2000–2019)",
    passage="Stage IV vs I–III, low vs high education: men OR 1.10 (1.08–1.12), women 1.15 "
    "(1.13–1.17). Cancer-specific mortality, adjusted for age, year, stage, treatment, birth "
    "year, marital status, origin, region and urbanisation: men HR 1.13 (1.10–1.16), women "
    "1.14 (1.11–1.17); lung, women 1.22 (1.12–1.33). Surgery: lung, women OR 0.85 (0.78–0.93).",
    grade=EvidenceGrade.REGISTRY,
    url="https://pmc.ncbi.nlm.nih.gov/articles/PMC12551501/",
    source_id="01a1da05-3598-7096-9343-213d624b78c7",
)
NORDCAN = Citation(
    source="NORDCAN 5-year relative survival by site, Nordic countries, 2020-2024, read from "
    "ADA's operator op_fbd206c1d7b01ba0e8be5e09598bb74f (source 01a1da4c-1a05-76a4-a931-"
    "7075fec66d53)",
    passage="Rows for cancer 160 (lung), 520 (colorectal) and 130 (pancreas), period 2020-2024, "
    "sex 1 (men) and 2 (women), countries Norway, Sweden and Finland; the Nordic level is "
    "the mean of Sweden and Norway, as the National Cancer Strategy defines it.",
    grade=EvidenceGrade.REGISTRY,
    url="https://canapi.iarc.who.int/api/nordcan/v2/961/survival/population/5/1_2/208_246",
    operator_id="op_fbd206c1d7b01ba0e8be5e09598bb74f",
    run_id="01a1db11-d2fa-7782-95dd-aa41a3277464",
    source_id="01a1da4c-1a05-76a4-a931-7075fec66d53",
)
NORWAY_CRC = Citation(
    source="Helsedirektoratet, Pakkeforløp for tykk- og endetarmskreft (last revised 3 July 2026)",
    passage="Fra henvisning mottatt til første fremmøte: 10 kalenderdager; til avsluttet "
    "utredning: "
    "12; til start behandling: kirurgisk 14, medikamentell 14, strålebehandling 18; fra "
    "henvisning mottatt til start behandling: 36 / 36 / 40. Begrunnet mistanke hos pasienter "
    "over 40 år: uavklart blødning fra tarmen; funn av tumor eller polypp ved ano-/rektoskopi; "
    "endring av et ellers stabilt avføringsmønster i over fire uker.",
    grade=EvidenceGrade.STANDARD,
    url="https://www.helsedirektoratet.no/nasjonale-forlop/tykk-og-endetarmskreft",
    source_id="01a1dc00-f98a-70b1-bf3e-5f97c599e2a6",
    country="Norway",
)
NORWAY_PANCREAS = Citation(
    source="Helsedirektoratet, Pakkeforløp for bukspyttkjertelkreft (last revised 3 July 2026)",
    passage="Fra henvisning mottatt til første fremmøte: 8 kalenderdager; til avsluttet utredning: "
    "21; til start behandling: kirurgisk 14, medikamentell 14; fra henvisning mottatt til start "
    "behandling: 43. Begrunnet mistanke: malignitetssuspekt lesjon i bukspyttkjertelen ved "
    "bildediagnostikk; ikterus uten opplagt forklaring.",
    grade=EvidenceGrade.STANDARD,
    url="https://www.helsedirektoratet.no/nasjonale-forlop/bukspyttkjertelkreft",
    source_id="01a1dc00-fa01-742a-a14c-29de1a8d4364",
    country="Norway",
)
SWEDEN_CRC = Citation(
    source="Regionala cancercentrum, SVF tjock- och ändtarmscancer, version 4.3 (2026-05-04)",
    passage="Misstanke (över 40 år): blod i avföringen; anemi; ändring av avföringsvanor > 4 "
    "veckor; "
    "undersökningar inom 10 kalenderdagar. Välgrundad misstanke: synligt blod utan annan "
    "blödningskälla; järnbristanemi utan annan orsak; ändrade avföringsvanor > 4 veckor med "
    "positivt FHb; fynd vid prokto-/rektoskopi eller palpation; fynd vid bild-, vävnads- eller "
    "koloskopidiagnostik. Ledtider: beslut välgrundad misstanke till första behandling 46 "
    "kalenderdagar (palliativt behandlingsbeslut 25); remiss mottagen 1; första besök 10; "
    "basutredning till behandlingsbeslut 14; beslut till start 21.",
    grade=EvidenceGrade.STANDARD,
    url="https://kunskapsbanken.cancercentrum.se/globalassets/cancerdiagnoser/tjock--och-andtarm-anal/vardforlopp/svf-tjock-andtarmscancer.pdf",
    country="Sweden",
    source_id="01a1db1c-e785-76a8-a206-9c34a094e33a",
)
SWEDEN_PANCREAS = Citation(
    source="Regionala cancercentrum, SVF cancer i bukspottkörteln och periampullärt, version 3.2 "
    "(2024-11-05)",
    passage="Misstanke: gulsot eller gallstas; palpabel knöl i övre buken; smärta i övre buken "
    "eller "
    "ryggen med ofrivillig viktnedgång, särskilt vid nydebuterad diabetes eller steatorré. "
    "Välgrundad misstanke: bilddiagnostiskt eller endoskopiskt fynd talande för potentiellt "
    "malign förändring; MR-fynd av sidogångs-IPMN med kirurgikriterier; gallstas ej kopplad till "
    "gallstens- eller leversjukdom; cyto- eller histopatologiskt fynd; misstanke vid bukoperation. "
    "Ledtider: beslut välgrundad misstanke till första behandling, kirurgi 36, läkemedel 29, "
    "palliativ 22 kalenderdagar; remiss mottagen 1; första besök 7; block A till MDK 7; MDK till "
    "behandlingsbeslut 7-14; beslut till start 7.",
    grade=EvidenceGrade.STANDARD,
    url="https://kunskapsbanken.cancercentrum.se/globalassets/cancerdiagnoser/bukspottkortel/vardforlopp/svf-bukspottkortelcancer.pdf",
    country="Sweden",
    source_id="01a1db1c-e7b1-721d-9e02-a0379411cde7",
)
HANNA_CRC = HANNA.model_copy(
    update={
        "passage": "Colectomy: hazard ratio 1.06 (95% CI 1.01 to 1.12) per four-week delay from "
        "diagnosis to surgery, overall survival; log-linearity between four and 16 weeks."
    }
)
PANCREAS_DELAY = Citation(
    source="No pancreas-specific delay effect exists in Hanna 2020; Sanjeevi et al., Br J Surg "
    "2016 "
    "(abstract) found that operating within 32 days of imaging halved progression to "
    "unresectable disease",
    passage="The surgical range of Hanna 2020 (1.06-1.08 per four weeks) is borrowed as an "
    "assumption, with a confidence interval that includes no effect.",
    grade=EvidenceGrade.ASSUMPTION,
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
    source_id="01a1dc00-fba8-71d5-b822-38ac0e55023b",
)

POKHREL = Citation(
    source="Pokhrel et al., Br J Cancer 2010;103:1109-14 (PMC2965870)",
    passage="Table 1, 1996-2005, 5-year cancer-specific survival by education, lung: women "
    "18.8 % (high) / 13.5 % (secondary) / 12.3 % (basic); men 10.6 / 9.5 / 9.2 %.",
    grade=EvidenceGrade.REGISTRY,
    url="https://pmc.ncbi.nlm.nih.gov/articles/PMC2965870/",
    source_id="01a1dc00-fb5c-7686-b8a2-19282fd57961",
)

DENMARK = Citation(
    source="Sundhedsstyrelsen, Pakkeforløb for lungekræft, for fagfolk, version 2.2 (2024-12-10)",
    passage="Fra henvisning modtaget til første fremmøde på udredende afdeling 6 kalenderdage; "
    "til afslutning af udredning 24; fra afslutning af udredning til start på initial "
    "behandling: kirurgisk 14, medicinsk 11, strålebehandling 15; samlet forløbstid 44 / 41 / 45. "
    "Kriterier for henvisning: malignitetssuspekt lungeinfiltrat eller tumor i mediastinum ved "
    "billeddiagnostisk undersøgelse; biopsi fra metastase tyder på primært udgangspunkt i lungen; "
    "meget klare sygdomsrelaterede symptomer, uanset om et nyligt røntgen af thorax er normalt. "
    "Over 40 år med relevant tobaksanamnese bør lægen overveje CT ved hoste af mere end 4-6 ugers "
    "varighed, brystsmerter, skuldersmerter; ved hæmoptyse uanset alder.",
    grade=EvidenceGrade.STANDARD,
    url="https://www.sst.dk/media/estk2oo1/pakkeforloeb-for-lungekraeft-jan-2025.pdf",
    country="Denmark",
    source_id="01a1dc05-6d93-73af-a6d6-df162af64956",
)
DENMARK_CRC = Citation(
    source="Sundhedsstyrelsen, Pakkeforløb for kræft i tyk- og endetarm, for fagfolk (2022)",
    passage="Fra henvisning modtaget til første fremmøde 9 kalenderdage; til afslutning af "
    "udredning 18; til start på initial behandling: kirurgi 10, strålebehandling 14, "
    "medicinsk-onkologisk 10; samlet forløbstid 37 / 41 / 37. Særligt over 40 år: blødning fra "
    "tarmen uden anden oplagt årsag; ændring af et ellers stabilt afføringsmønster i over fire "
    "uger; uforklaret blødningsanæmi/jernmangelanæmi; nytilkomne mavesmerter over 4 uger. "
    "Kriterier for henvisning: mistanke om eller konstateret malignitet ved koloskopi; fund af "
    "metastaser, der giver mistanke om udgangspunkt i tyk- og endetarm.",
    grade=EvidenceGrade.STANDARD,
    url="https://www.sst.dk/media/ovabkmzr/pakkeforloeb.pdf",
    country="Denmark",
    source_id="01a1dc05-6de9-750f-8933-c33653ccfe3a",
)
DENMARK_PANCREAS = Citation(
    source="Sundhedsstyrelsen, Pakkeforløb for kræft i bugspytkirtel, galdegange og lever, for "
    "fagfolk (2021)",
    passage="Fra henvisning modtaget til første fremmøde 6 kalenderdage; til afslutning af "
    "udredning 27; til start på initial behandling: kirurgisk 10, medicinsk 11; samlet "
    "forløbstid 43 / 44. Kriterier for henvisning: gulsot uden oplagt forklaring; "
    "billeddiagnostisk påvisning af tumor i bugspytkirtlen, tolvfingertarmen eller det "
    "periampullære område; billeddiagnostisk uafklaret proces i bugspytkirtlen.",
    grade=EvidenceGrade.STANDARD,
    url="https://www.sst.dk/media/kpznsa1b/pakkeforloeb-for-kraeft-bugl.pdf",
    country="Denmark",
    source_id="01a1dc05-6e36-7706-a237-081e4ad9b459",
)

LUNG, COLORECTAL, PANCREAS = "lung", "colorectal", "pancreas"
# NORDCAN's own age groups for survival; no interpolation between them.
AGE_BANDS = ("00-49", "50-59", "60-69", "70-79", "80-89")
FEMALE, MALE = "female", "male"


def _criterion(
    site: str,
    id: str,
    stage: TriggerStage,
    text: str,
    countries: tuple[str, ...],
    provenance: Citation,
) -> Criterion:
    return Criterion(
        id=id, site=site, stage=stage, text=text, countries=countries, provenance=provenance
    )


def _lung_criteria() -> tuple[Criterion, ...]:
    S, W = TriggerStage.SUSPICION, TriggerStage.WELL_FOUNDED
    c = lambda *a: _criterion(LUNG, *a)  # noqa: E731
    return (
        c(
            "lung_symptoms_smoker",
            S,
            "New airway symptoms (cough, breathlessness) for 6 weeks in a smoker or ex-smoker "
            "over 40",
            ("Sweden",),
            SWEDEN_SUSPICION,
        ),
        c(
            "lung_cough_dk",
            S,
            "Cough for more than 4-6 weeks, or a changed cough, over 40 with a smoking history",
            ("Denmark",),
            DENMARK,
        ),
        c(
            "lung_chest_pain",
            S,
            "Chest or shoulder pain without another explanation",
            ("Sweden",),
            SWEDEN_SUSPICION,
        ),
        c(
            "lung_chest_pain_dk",
            S,
            "Chest or shoulder pain, over 40 with a smoking history",
            ("Denmark",),
            DENMARK,
        ),
        c("lung_haemoptysis", S, "Coughing blood", ("Denmark", "Sweden"), SWEDEN_SUSPICION),
        c(
            "lung_imaging",
            W,
            "Imaging finding suggesting lung cancer",
            ("Denmark", "Norway", "Sweden"),
            SWEDEN_WELL_FOUNDED,
        ),
        c(
            "lung_metastasis",
            W,
            "A metastasis or a biopsy from another organ suggesting lung cancer",
            ("Denmark", "Norway", "Sweden"),
            NORWAY_CRITERIA,
        ),
        c(
            "lung_repeated_haemoptysis",
            W,
            "Repeated haemoptysis without another obvious cause, even with a normal X-ray",
            ("Sweden",),
            SWEDEN_WELL_FOUNDED,
        ),
        c(
            "lung_clear_symptoms",
            W,
            "Very clear symptoms of lung cancer, even with a recent normal chest X-ray",
            ("Denmark",),
            DENMARK,
        ),
        c("lung_svc", W, "Superior vena cava obstruction", ("Sweden",), SWEDEN_WELL_FOUNDED),
        c(
            "lung_recurrent_nerve",
            W,
            "Recurrent laryngeal nerve palsy",
            ("Sweden",),
            SWEDEN_WELL_FOUNDED,
        ),
    )


def _colorectal_criteria() -> tuple[Criterion, ...]:
    S, W = TriggerStage.SUSPICION, TriggerStage.WELL_FOUNDED
    c = lambda *a: _criterion(COLORECTAL, *a)  # noqa: E731
    return (
        c("crc_blood", S, "Blood in the stool, over 40", ("Sweden",), SWEDEN_CRC),
        c(
            "crc_bleeding_dk",
            S,
            "Bleeding from the bowel without another obvious cause, especially over 40",
            ("Denmark",),
            DENMARK_CRC,
        ),
        c("crc_anaemia", S, "Anaemia, over 40", ("Sweden",), SWEDEN_CRC),
        c(
            "crc_anaemia_dk",
            S,
            "Unexplained bleeding anaemia or iron-deficiency anaemia, especially over 40",
            ("Denmark",),
            DENMARK_CRC,
        ),
        c(
            "crc_habit_change",
            S,
            "A change of otherwise stable bowel habits for more than 4 weeks, over 40",
            ("Denmark", "Sweden"),
            SWEDEN_CRC,
        ),
        c(
            "crc_abdominal_pain",
            S,
            "New abdominal pain persisting for more than 4 weeks, over 40",
            ("Denmark",),
            DENMARK_CRC,
        ),
        c(
            "crc_unexplained_bleeding",
            W,
            "Visible blood in the stool with no other source found at rectal examination and "
            "procto- or rectoscopy",
            ("Norway", "Sweden"),
            SWEDEN_CRC,
        ),
        c(
            "crc_iron_deficiency",
            W,
            "Iron-deficiency anaemia without another obvious cause",
            ("Sweden",),
            SWEDEN_CRC,
        ),
        c(
            "crc_habit_change_fhb",
            W,
            "Changed bowel habits for more than 4 weeks, over 40, with a positive faecal blood "
            "test",
            ("Norway", "Sweden"),
            SWEDEN_CRC,
        ),
        c(
            "crc_rectoscopy_finding",
            W,
            "A finding at procto- or rectoscopy or rectal palpation suggesting colorectal cancer",
            ("Norway", "Sweden"),
            NORWAY_CRC,
        ),
        c(
            "crc_imaging_finding",
            W,
            "A finding at imaging, tissue diagnostics or colonoscopy suggesting colorectal cancer",
            ("Denmark", "Sweden"),
            SWEDEN_CRC,
        ),
        c(
            "crc_metastasis",
            W,
            "Metastases suggesting colorectal cancer as the origin",
            ("Denmark",),
            DENMARK_CRC,
        ),
    )


def _pancreas_criteria() -> tuple[Criterion, ...]:
    S, W = TriggerStage.SUSPICION, TriggerStage.WELL_FOUNDED
    c = lambda *a: _criterion(PANCREAS, *a)  # noqa: E731
    return (
        c("panc_jaundice", S, "Jaundice or cholestasis", ("Sweden",), SWEDEN_PANCREAS),
        c("panc_mass", S, "A palpable mass in the upper abdomen", ("Sweden",), SWEDEN_PANCREAS),
        c(
            "panc_pain_weight_loss",
            S,
            "Upper abdominal or back pain with unintended weight loss, especially with new "
            "diabetes or steatorrhoea",
            ("Sweden",),
            SWEDEN_PANCREAS,
        ),
        c(
            "panc_imaging",
            W,
            "An imaging or endoscopic finding of a potentially malignant change in the pancreas or "
            "periampullary region",
            ("Denmark", "Norway", "Sweden"),
            SWEDEN_PANCREAS,
        ),
        c(
            "panc_cholestasis",
            W,
            "Cholestasis or jaundice not explained by gallstone or liver disease",
            ("Denmark", "Norway", "Sweden"),
            NORWAY_PANCREAS,
        ),
        c(
            "panc_unclear_process",
            W,
            "An unclear process in the pancreas at imaging",
            ("Denmark",),
            DENMARK_PANCREAS,
        ),
        c(
            "panc_ipmn",
            W,
            "MRI finding of a side-branch IPMN meeting the criteria for surgery",
            ("Sweden",),
            SWEDEN_PANCREAS,
        ),
        c(
            "panc_pathology",
            W,
            "A cytological or histopathological finding of malignancy in the pancreas or "
            "periampullary region",
            ("Sweden",),
            SWEDEN_PANCREAS,
        ),
        c(
            "panc_at_surgery",
            W,
            "Suspected malignancy found at abdominal surgery",
            ("Sweden",),
            SWEDEN_PANCREAS,
        ),
    )


def _targets() -> tuple[TargetTime, ...]:
    P = PathwayStep
    SU, RT, DR = Modality.SURGERY, Modality.RADIOTHERAPY, Modality.DRUGS

    DK, SE = (DENMARK,), (SWEDEN,)
    CRC, PAN = (DENMARK_CRC, SWEDEN_CRC), (DENMARK_PANCREAS, SWEDEN_PANCREAS)

    def t(site, step, days, provenance, modality=None, also=()):
        return TargetTime(
            site=site,
            step=step,
            modality=modality,
            days_by_country=days,
            provenance=provenance,
            other_sources=also,
        )

    return (
        # Lung
        t(LUNG, P.CONTACT_TO_PHYSICIAN, {"Nordic reference": 7}, KHALIFE),
        t(LUNG, P.PHYSICIAN_TO_IMAGING, {"Sweden": 6}, SWEDEN),
        t(LUNG, P.IMAGING_TO_REFERRAL, {"Sweden": 4}, SWEDEN),
        t(LUNG, P.REFERRAL_TO_SPECIALIST, {"Norway": 7, "Denmark": 6}, NORWAY, also=DK),
        t(LUNG, P.SPECIALIST_TO_WORKUP, {"Norway": 21, "Denmark": 24}, NORWAY, also=DK),
        t(LUNG, P.WORKUP_TO_TREATMENT, {"Norway": 14, "Denmark": 14}, NORWAY, SU, DK),
        t(LUNG, P.WORKUP_TO_TREATMENT, {"Norway": 14, "Denmark": 15}, NORWAY, RT, DK),
        t(LUNG, P.WORKUP_TO_TREATMENT, {"Norway": 7, "Denmark": 11}, NORWAY, DR, DK),
        t(LUNG, None, {"Norway": 42, "Sweden": 44, "Denmark": 44}, NORWAY, SU, DK + SE),
        t(LUNG, None, {"Norway": 42, "Sweden": 44, "Denmark": 45}, NORWAY, RT, DK + SE),
        t(LUNG, None, {"Norway": 35, "Sweden": 40, "Denmark": 41}, NORWAY, DR, DK + SE),
        # Colorectal: Sweden's investigations within 10 days of suspicion stand for the step to
        # the finding; the referral is received a day after the decision.
        t(COLORECTAL, P.PHYSICIAN_TO_IMAGING, {"Sweden": 10}, SWEDEN_CRC),
        t(COLORECTAL, P.IMAGING_TO_REFERRAL, {"Sweden": 1}, SWEDEN_CRC),
        t(
            COLORECTAL,
            P.REFERRAL_TO_SPECIALIST,
            {"Norway": 10, "Sweden": 10, "Denmark": 9},
            NORWAY_CRC,
            also=CRC,
        ),
        t(
            COLORECTAL,
            P.SPECIALIST_TO_WORKUP,
            {"Norway": 12, "Sweden": 14, "Denmark": 18},
            NORWAY_CRC,
            also=CRC,
        ),
        t(
            COLORECTAL,
            P.WORKUP_TO_TREATMENT,
            {"Norway": 14, "Sweden": 21, "Denmark": 10},
            NORWAY_CRC,
            SU,
            CRC,
        ),
        t(
            COLORECTAL,
            P.WORKUP_TO_TREATMENT,
            {"Norway": 18, "Sweden": 21, "Denmark": 14},
            NORWAY_CRC,
            RT,
            CRC,
        ),
        t(
            COLORECTAL,
            P.WORKUP_TO_TREATMENT,
            {"Norway": 14, "Sweden": 21, "Denmark": 10},
            NORWAY_CRC,
            DR,
            CRC,
        ),
        t(
            COLORECTAL,
            None,
            {"Norway": 36, "Sweden": 46, "Denmark": 37},
            NORWAY_CRC,
            SU,
            CRC,
        ),
        t(
            COLORECTAL,
            None,
            {"Norway": 40, "Sweden": 46, "Denmark": 41},
            NORWAY_CRC,
            RT,
            CRC,
        ),
        t(
            COLORECTAL,
            None,
            {"Norway": 36, "Sweden": 46, "Denmark": 37},
            NORWAY_CRC,
            DR,
            CRC,
        ),
        # Pancreas
        t(PANCREAS, P.IMAGING_TO_REFERRAL, {"Sweden": 1}, SWEDEN_PANCREAS),
        t(
            PANCREAS,
            P.REFERRAL_TO_SPECIALIST,
            {"Norway": 8, "Sweden": 7, "Denmark": 6},
            NORWAY_PANCREAS,
            also=PAN,
        ),
        t(
            PANCREAS,
            P.SPECIALIST_TO_WORKUP,
            {"Norway": 21, "Sweden": 14, "Denmark": 27},
            NORWAY_PANCREAS,
            also=PAN,
        ),
        t(
            PANCREAS,
            P.WORKUP_TO_TREATMENT,
            {"Norway": 14, "Sweden": 7, "Denmark": 10},
            NORWAY_PANCREAS,
            SU,
            PAN,
        ),
        t(
            PANCREAS,
            P.WORKUP_TO_TREATMENT,
            {"Norway": 14, "Sweden": 7, "Denmark": 11},
            NORWAY_PANCREAS,
            DR,
            PAN,
        ),
        t(
            PANCREAS,
            None,
            {"Norway": 43, "Sweden": 36, "Denmark": 43},
            NORWAY_PANCREAS,
            SU,
            PAN,
        ),
        t(
            PANCREAS,
            None,
            {"Norway": 43, "Sweden": 29, "Denmark": 44},
            NORWAY_PANCREAS,
            DR,
            PAN,
        ),
    )


NORDCAN_BY_AGE = NORDCAN.model_copy(
    update={
        "source": "NORDCAN 5-year relative survival by site, sex and age group, Norway and Sweden, "
        "2020-2024 (canapi.iarc.who.int, age_surv=1, read directly on 2026-11-14)",
        "passage": "Age groups 00-49, 50-59, 60-69, 70-79 and 80-89 for cancers 160, 520 and 130; "
        "the Nordic level is the mean of Norway and Sweden per cell.",
        "url": "https://canapi.iarc.who.int/api/nordcan/v2/961/survival/population/5/1_2/246_578_752/160_130_520/?&surv_period=5&age_surv=1&year_start=2020&year_end=2024",  # noqa: E501
        "operator_id": None,
        "run_id": None,
    }
)

# (site, sex, NORDCAN age group, the mean of Norway and Sweden), from NORDCAN_BY_AGE.
NORDIC_BY_AGE = (
    (LUNG, MALE, "00-49", 0.4545),  # Norway 45.3, Sweden 45.6
    (LUNG, MALE, "50-59", 0.354),  # Norway 34.1, Sweden 36.7
    (LUNG, MALE, "60-69", 0.3185),  # Norway 31.9, Sweden 31.8
    (LUNG, MALE, "70-79", 0.278),  # Norway 28.1, Sweden 27.5
    (LUNG, MALE, "80-89", 0.194),  # Norway 18.6, Sweden 20.2
    (LUNG, FEMALE, "00-49", 0.582),  # Norway 54.7, Sweden 61.7
    (LUNG, FEMALE, "50-59", 0.4405),  # Norway 41.8, Sweden 46.3
    (LUNG, FEMALE, "60-69", 0.3925),  # Norway 41.5, Sweden 37.0
    (LUNG, FEMALE, "70-79", 0.343),  # Norway 35.2, Sweden 33.4
    (LUNG, FEMALE, "80-89", 0.244),  # Norway 22.5, Sweden 26.3
    (COLORECTAL, MALE, "00-49", 0.763),  # Norway 75.5, Sweden 77.1
    (COLORECTAL, MALE, "50-59", 0.736),  # Norway 75.6, Sweden 71.6
    (COLORECTAL, MALE, "60-69", 0.7365),  # Norway 74.7, Sweden 72.6
    (COLORECTAL, MALE, "70-79", 0.7015),  # Norway 70.0, Sweden 70.3
    (COLORECTAL, MALE, "80-89", 0.671),  # Norway 65.3, Sweden 68.9
    (COLORECTAL, FEMALE, "00-49", 0.7825),  # Norway 79.3, Sweden 77.2
    (COLORECTAL, FEMALE, "50-59", 0.7475),  # Norway 76.7, Sweden 72.8
    (COLORECTAL, FEMALE, "60-69", 0.743),  # Norway 74.7, Sweden 73.9
    (COLORECTAL, FEMALE, "70-79", 0.7065),  # Norway 70.8, Sweden 70.5
    (COLORECTAL, FEMALE, "80-89", 0.6945),  # Norway 71.1, Sweden 67.8
    (PANCREAS, MALE, "00-49", 0.4435),  # Norway 43.4, Sweden 45.3
    (PANCREAS, MALE, "50-59", 0.215),  # Norway 24.1, Sweden 18.9
    (PANCREAS, MALE, "60-69", 0.1525),  # Norway 16.5, Sweden 14.0
    (PANCREAS, MALE, "70-79", 0.1235),  # Norway 13.1, Sweden 11.6
    (PANCREAS, MALE, "80-89", 0.0885),  # Norway 7.6, Sweden 10.1
    (PANCREAS, FEMALE, "00-49", 0.4935),  # Norway 52.8, Sweden 45.9
    (PANCREAS, FEMALE, "50-59", 0.2765),  # Norway 32.7, Sweden 22.6
    (PANCREAS, FEMALE, "60-69", 0.1635),  # Norway 15.5, Sweden 17.2
    (PANCREAS, FEMALE, "70-79", 0.1115),  # Norway 11.6, Sweden 10.7
    (PANCREAS, FEMALE, "80-89", 0.044),  # Norway 3.8, Sweden 5.0
)


EXPECTED = Citation(
    source="Eurostat life tables (demo_mlifetable), probability of dying by single year of age, "
    "Norway and Sweden, 2023, read from ADA's operator op_dd316aef48492f45b723dae5485635b7 "
    "(source 01a1dc1c-d97e-7164-bedd-3ed945fd9f88)",
    passage="5-year expected survival from the product of (1 - q) over five single years from "
    "the start age (45, 55, 65, 75 and 85 for the age groups; 70 for all ages), the mean of "
    "Norway and Sweden. The excess share of the hazard is ln R / ln(R x E), with R the "
    "relative survival: exact when both hazards are constant over the five years, which "
    "they are not (the excess hazard is front-loaded), so it is an approximation.",
    grade=EvidenceGrade.REGISTRY,
    url="https://ec.europa.eu/eurostat/databrowser/view/demo_mlifetable/default/table",
    operator_id="op_dd316aef48492f45b723dae5485635b7",
    run_id="01a1dc1c-f122-767c-a671-032582bb77f7",
    source_id="01a1dc1c-d97e-7164-bedd-3ed945fd9f88",
)

# 5-year expected survival by sex and age group, the mean of Norway and Sweden (EXPECTED).
EXPECTED_5Y = {
    (FEMALE, "00-49"): 0.9948,
    (FEMALE, "50-59"): 0.9861,
    (FEMALE, "60-69"): 0.9614,
    (FEMALE, "70-79"): 0.8867,
    (FEMALE, "80-89"): 0.6360,
    (FEMALE, None): 0.9366,
    (MALE, "00-49"): 0.9925,
    (MALE, "50-59"): 0.9803,
    (MALE, "60-69"): 0.9434,
    (MALE, "70-79"): 0.8437,
    (MALE, "80-89"): 0.5405,
    (MALE, None): 0.9074,
}


NORWAY_BY_STAGE = Citation(
    source="Cancer in Norway 2025, Tables 7.3 and 7.4: five-year relative survival by site, stage "
    "and period, 2021-25 (period approach), read from ADA's operator "
    "op_b5a128ed84a5077376a87b274ce7de56 (source 01a1dc1e-0fda-75f3-a3a0-1e28d921f5ee)",
    passage="C33-34 Lung, trachea, C18-20 Colorectal and C25 Pancreas: the Localised, Regional and "
    "Distant rows, last column (2021-25), men and women. Norway's own figures stand in for the "
    "Nordic level by stage: Sweden publishes none in this form. Age-standardised by the "
    "registry, so they apply to every age group.",
    grade=EvidenceGrade.REGISTRY,
    url="https://www.fhi.no/Content/cancer-in-norway-2025.pdf",
    country="Norway",
    operator_id="op_b5a128ed84a5077376a87b274ce7de56",
    run_id="01a1dc22-e630-717c-abdd-f6382f78c468",
    source_id="01a1dc1e-0fda-75f3-a3a0-1e28d921f5ee",
)

# (site, sex, stage, 5-year relative survival %), from NORWAY_BY_STAGE.
NORWAY_STAGE = (
    (LUNG, MALE, "localised", 65.7),
    (LUNG, MALE, "regional", 33.9),
    (LUNG, MALE, "distant", 8.6),
    (LUNG, FEMALE, "localised", 72.3),
    (LUNG, FEMALE, "regional", 42.1),
    (LUNG, FEMALE, "distant", 10.4),
    (COLORECTAL, MALE, "localised", 95.5),
    (COLORECTAL, MALE, "regional", 83.6),
    (COLORECTAL, MALE, "distant", 21.5),
    (COLORECTAL, FEMALE, "localised", 97.4),
    (COLORECTAL, FEMALE, "regional", 86.1),
    (COLORECTAL, FEMALE, "distant", 22.5),
    (PANCREAS, MALE, "localised", 45.8),
    (PANCREAS, MALE, "regional", 23.9),
    (PANCREAS, MALE, "distant", 3.9),
    (PANCREAS, FEMALE, "localised", 47.7),
    (PANCREAS, FEMALE, "regional", 22.8),
    (PANCREAS, FEMALE, "distant", 3.8),
)


def excess_share(relative: float, expected: float) -> float:
    """The share of the hazard over five years that is excess: ln R / ln(R x E)."""
    return round(math.log(relative) / math.log(relative * expected), 4)


def _baseline() -> tuple[BaselineCell, ...]:
    # The mean of Sweden and Norway, 2020-2024, from the NORDCAN operator (NORDCAN citation).
    nordic = {
        (LUNG, MALE): (30.8 + 31.3) / 2,
        (LUNG, FEMALE): (38.4 + 38.9) / 2,
        (COLORECTAL, MALE): (72.2 + 71.7) / 2,
        (COLORECTAL, FEMALE): (73.9 + 72.2) / 2,
        (PANCREAS, MALE): (18.7 + 17.3) / 2,
        (PANCREAS, FEMALE): (20.0 + 17.9) / 2,
    }
    all_ages = tuple(
        BaselineCell(
            site=site,
            sex=sex,
            survival=round(pct / 100, 4),
            excess_share=excess_share(pct / 100, EXPECTED_5Y[sex, None]),
            provenance=NORDCAN,
        )
        for (site, sex), pct in nordic.items()
    )
    by_age = tuple(
        BaselineCell(
            site=site,
            sex=sex,
            age_band=age,
            survival=survival,
            excess_share=excess_share(survival, EXPECTED_5Y[sex, age]),
            provenance=NORDCAN_BY_AGE,
        )
        for site, sex, age, survival in NORDIC_BY_AGE
    )
    by_stage = tuple(
        BaselineCell(
            site=site,
            sex=sex,
            stage=stage,
            survival=round(pct / 100, 4),
            excess_share=excess_share(pct / 100, EXPECTED_5Y[sex, None]),
            provenance=NORWAY_BY_STAGE,
        )
        for site, sex, stage, pct in NORWAY_STAGE
    )
    return all_ages + by_age + by_stage


def _parameter(name, estimate, lo, hi, scale, form, provenance):
    return Parameter(
        name=name,
        estimate=estimate,
        ci_low=lo,
        ci_high=hi,
        scale=scale,
        form=form,
        provenance=provenance,
    )


def pathway_spec() -> ModelSpec:
    OV, CS, OR_ = Scale.OVERALL, Scale.CAUSE_SPECIFIC, Scale.ODDS_RATIO
    F = Form
    return ModelSpec(
        outcome="5-year relative survival",
        sites=(LUNG, COLORECTAL, PANCREAS),
        terms=(
            Term(name="sex", levels=(FEMALE, MALE), reference=FEMALE),
            Term(name="age_band", levels=AGE_BANDS, reference="60-69"),
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
        criteria=_lung_criteria() + _colorectal_criteria() + _pancreas_criteria(),
        targets=_targets(),
        baseline=_baseline(),
        parameters={
            NO_PATHWAY: _parameter(NO_PATHWAY, *NO_PATHWAY_RATIO, Scale.RATIO, F.VALUE, JENSEN),
            "heiden_lung_surgery": _parameter(
                "heiden_lung_surgery", 1.132, 1.064, 1.204, OV, F.BEYOND_12_WEEKS, HEIDEN
            ),
            "hanna_lung_surgery": _parameter(
                "hanna_lung_surgery", 1.06, 0.93, 1.19, OV, F.PER_4_WEEKS, HANNA
            ),
            "hanna_colectomy": _parameter(
                "hanna_colectomy", 1.06, 1.01, 1.12, OV, F.PER_4_WEEKS, HANNA_CRC
            ),
            "pancreas_delay_assumed": _parameter(
                "pancreas_delay_assumed", 1.06, 1.00, 1.12, OV, F.PER_4_WEEKS, PANCREAS_DELAY
            ),
            "sud_per_day": _parameter(
                "sud_per_day", 0.0056, 0.0056 * 0.92, 0.0056 * 1.08, OV, F.PER_DAY, SUD
            ),
            "zai_stage_or_men": _parameter(
                "zai_stage_or_men", 1.10, 1.08, 1.12, OR_, F.ODDS_RATIO, ZAI
            ),
            "zai_stage_or_women": _parameter(
                "zai_stage_or_women", 1.15, 1.13, 1.17, OR_, F.ODDS_RATIO, ZAI
            ),
            "zai_stage_or_crc_men": _parameter(
                "zai_stage_or_crc_men", 1.10, 1.05, 1.15, OR_, F.ODDS_RATIO, ZAI
            ),
            "zai_stage_or_crc_women": _parameter(
                "zai_stage_or_crc_women", 1.09, 1.05, 1.15, OR_, F.ODDS_RATIO, ZAI
            ),
            "zai_direct_men": _parameter(
                "zai_direct_men", 1.13, 1.10, 1.16, CS, F.HAZARD_RATIO, ZAI
            ),
            "zai_direct_women": _parameter(
                "zai_direct_women", 1.14, 1.11, 1.17, CS, F.HAZARD_RATIO, ZAI
            ),
            "zai_direct_lung_women": _parameter(
                "zai_direct_lung_women", 1.22, 1.12, 1.33, CS, F.HAZARD_RATIO, ZAI
            ),
            "zai_direct_crc_women": _parameter(
                "zai_direct_crc_women", 1.13, 1.04, 1.22, CS, F.HAZARD_RATIO, ZAI
            ),
        },
        arrows={
            "delay_post:lung:surgery": "heiden_lung_surgery",
            "delay_post:lung": "hanna_lung_surgery",
            "delay_post:colorectal": "hanna_colectomy",
            "delay_post:pancreas": "pancreas_delay_assumed",
            "delay_pre": "sud_per_day",
            "stage_education:lung:male": "zai_stage_or_men",
            "stage_education:lung:female": "zai_stage_or_women",
            "stage_education:colorectal:male": "zai_stage_or_crc_men",
            "stage_education:colorectal:female": "zai_stage_or_crc_women",
            "stage_education": "zai_stage_or_women",
            "direct_education:lung:female": "zai_direct_lung_women",
            "direct_education:colorectal:female": "zai_direct_crc_women",
            "direct_education:lung:male": "zai_direct_men",
            "direct_education:colorectal:male": "zai_direct_men",
            "direct_education:pancreas:male": "zai_direct_men",
            "direct_education:pancreas:female": "zai_direct_women",
        },
        comparison=ComparisonPopulation(
            country="Finland",
            # NORDCAN, Finland, 2020-2024, from the same operator and run.
            survival={
                f"{LUNG}:{MALE}": 0.179,
                f"{LUNG}:{FEMALE}": 0.308,
                f"{COLORECTAL}:{MALE}": 0.696,
                f"{COLORECTAL}:{FEMALE}": 0.728,
                f"{PANCREAS}:{MALE}": 0.121,
                f"{PANCREAS}:{FEMALE}": 0.136,
            },
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
            survival_by_education={
                f"{LUNG}:{FEMALE}:basic": 0.123,
                f"{LUNG}:{FEMALE}:tertiary": 0.188,
                f"{LUNG}:{MALE}:basic": 0.092,
                f"{LUNG}:{MALE}:tertiary": 0.106,
            },
            education_provenance=POKHREL,
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
                about="Sud's per-day rate on the days lost before the trigger. An assumption: part "
                "of it is lead time.",
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
            "An educational and planning tool that shows how a cancer pathway compares with the "
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
            "Finland's typical days per step are known for lung cancer only (a preliminary study); "
            "for the other sites the targets stand in.",
        ),
    )
