"""The sites each search scope looks at, shared by both search engines (Exa and
Context.dev). ANY looks everywhere; Context.dev searches NEWS in its own news index
instead of these sites."""

from ada.core.models.web import SearchScope

# Statistics offices, registries and open-data portals: THL/Sotkanet, Statistics Finland,
# the Finnish Cancer Registry and Cancer Society, the Nordic health data authorities and
# cancer centres, NORDCAN/IARC, Eurostat, OECD, WHO, Kela, Duodecim, open-data portals
# and repositories.
DATA_DOMAINS = [
    "sotkanet.fi",
    "thl.fi",
    "stat.fi",
    "pxdata.stat.fi",
    "syoparekisteri.fi",
    "cancerregistry.fi",
    "fican.fi",
    "sundhedsdatastyrelsen.dk",
    "helsedirektoratet.no",
    "cancercentrum.se",
    "iarc.who.int",
    "gco.iarc.fr",
    "ec.europa.eu",
    "oecd.org",
    "who.int",
    "kela.fi",
    "duodecim.fi",
    "avoindata.fi",
    "zenodo.org",
    "kaggle.com",
    "figshare.com",
]
NEWS_DOMAINS = [
    "reuters.com",
    "apnews.com",
    "bbc.com",
    "theguardian.com",
    "nytimes.com",
    "ft.com",
    "yle.fi",
    "hs.fi",
]
# Papers: PubMed and PubMed Central, preprint servers, journals and their publishers
# (Acta Oncologica at medicaljournalssweden.se).
RESEARCH_DOMAINS = [
    "pubmed.ncbi.nlm.nih.gov",
    "pmc.ncbi.nlm.nih.gov",
    "ncbi.nlm.nih.gov",
    "arxiv.org",
    "biorxiv.org",
    "medrxiv.org",
    "doi.org",
    "medicaljournalssweden.se",
    "bmj.com",
    "nature.com",
    "science.org",
    "thelancet.com",
    "sciencedirect.com",
    "springer.com",
    "tandfonline.com",
    "wiley.com",
    "academic.oup.com",
    "semanticscholar.org",
]
DOMAINS: dict[SearchScope, list[str] | None] = {
    SearchScope.DATA: DATA_DOMAINS,
    SearchScope.NEWS: NEWS_DOMAINS,
    SearchScope.RESEARCH: RESEARCH_DOMAINS,
    SearchScope.ANY: None,
}
