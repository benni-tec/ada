<!-- Exported from the design document on 2026-11-14. The document is the source; re-export rather than edit here. -->

# Agentic Data Analysis

Nov 14, 2026 · @Benjamin

An MCP server for traceable data analysis: an agent builds pipelines from data sources through statistics to widgets, and reports are assembled from those widgets. The focused demo targets Equal Care Across Finland (AstraZeneca); Context.dev is the bonus or fallback.

## Decisions so far

| Decision | Status |
| --- | --- |
| Primary demo is Equal Care Across Finland (AstraZeneca) | Settled |
| Context.dev is a bonus tech challenge, and the fallback main challenge if the healthcare data turns out thin | Settled |
| The data only validates the platform approach; it need not be complete | Settled |
| The core is an MCP server, usable from a local Claude session and from our own frontend | Settled |
| Projects contain sessions, dashboards and data sources; none is tied to a user | Settled |
| Pipelines are graphs of operators, materializing or pass-through | Settled |
| Two outputs: live monitoring dashboards, and reports frozen at a run | Settled |
| Reports are versioned with semantic versions under one name | Settled; what each level means is proposed |
| Time ranges are a first-class concept | Settled |
| Input operators make sources swappable, which gives simulation and templates | Settled |
| Recommendations come from an agent operator and are shown by a widget | Settled |
| Alerts are defined on pipelines, not on widgets | Settled; the condition is a formula tree in the rule |
| Definitions in a relational database, analysis data in DuckDB | Proposed |
| Optimistic locking on the few mutable records; everything else immutable | Proposed |
| Invalidation by parameter equality from above and freshness policies from below | Proposed |
| Operators and snapshots are stored per project and shared by its sessions and dashboards | Proposed |
| Widgets are the only data carriers and are written once as MCP Apps | Proposed |
| Stack (Python, DuckDB, React) | Implementation detail, deferred |

## Challenge fit

A project enters one main challenge and can add several tech challenges.

| Challenge | Company | Role | Why |
| --- | --- | --- | --- |
| Equal Care Across Finland | AstraZeneca | Primary | The brief lists "an AI analyst that explains indicator trends and proposes actions" as a possible solution. Data quality and transparency is 20% of the score, which traceable pipelines serve directly. Actionability is 30%, so the output must be a report that ends in recommendations. |
| Best Use of Context.dev | Context.dev | Bonus (tech) | Needs one endpoint in the core flow that visibly drives the demo. PDF parsing and web extraction as pipeline sources cover that. |
| The Web Is Your Real-Time Database | Context.dev | Fallback (main) | 20% of the score is reacting to change over time. Pipelines that re-run when a monitor fires would give that; a one-off analysis would not. |
| The Internet Butler | Exa | Not a fit | Asks for a personal agent that takes tedious everyday tasks off people's hands, with judges trying their own live queries. That is a different product. |
| Make Unicorns Real | Cala | Not a fit | Asks for a focused product for founders or investors with Cala at its core, and says focus beats breadth. The backend could run a market analysis on Cala data, but that would be a second product. |

## Partner check

None of the three partners analyses data natively; each is an acquisition layer that can feed pipelines.

| Partner | What it provides | What is missing |
| --- | --- | --- |
| Context.dev | Scrape, crawl, search, PDF and document parsing, schema-shaped answers with sources, monitors with webhooks, MCP server | No query interface over results, no statistics, no charts, no way to attach your own data |
| Exa | Semantic search, page contents, structured JSON results, Websets (verified and enriched lists), monitors, MCP server | Stops at the result table; nothing computes over it |
| Cala | Sourced knowledge graph of companies, people, funding rounds and investors, queryable by API or MCP | Lookup only, and the domain is the startup ecosystem, not health indicators |

The closer overlap is with general tools such as Julius, Hex or ChatGPT data analysis. The difference here is enforced traceability from every displayed number back to its source.

## Architecture

&#91;embedded content: architecture · three clients, one MCP server, one query layer\]

The operator graph is the core: because tools pass operator ids instead of data, every widget can be traced back to its sources without extra work from the agent.

## Projects, sessions and dashboards

A project is the top-level container. It holds sessions and dashboards, and neither belongs to a single user. What other sections call the workspace is a project.

- **Project**
  - **Data sources**: registered once, with address, access kind and freshness policy
  - **Sessions**: exploratory work led by the agent
    - Reports generated in the session
  - **Dashboards**: live monitoring
    - Alerts on the dashboard's pipelines
    - Reports generated from the dashboard
  - **Shared store**: operators, snapshots, runs, templates

|  | Session | Dashboard |
| --- | --- | --- |
| Purpose | Explore a question | Watch known indicators |
| Main component | The agent; widgets support the conversation | The widgets; the agent is a side panel |
| What the agent does | Finds sources, builds pipelines, creates widgets, drafts reports | Modifies the dashboard: adds or changes widgets, pipelines and alert rules |
| Lifetime | Ends when the question is answered; stays readable | Long-lived, refreshed by its sources |
| Data | Runs created as needed | Follows the latest run |
| Owns | Its reports | Its alerts and reports |

Moving between the two:

- **Dashboard to session.** A session can start from a dashboard, or from one of its alerts. It opens with the dashboard's pipelines, current run and time range, and records where it came from.
- **Session to dashboard.** A widget from a session can be pinned to a dashboard. Its pipeline then needs freshness policies on its sources, because it stops being a one-time result.

Consequences worth fixing now:

- **Operators and snapshots live in the project, not in the session.** Pinning a widget to a dashboard is then a reference, not a copy, and a source fetched in one session is reused in another.
- **A session is its record of operators and widgets, not a chat transcript.** When an external agent such as a local Claude session drives it over MCP, the conversation happens elsewhere, but every tool call still lands in the session.
- **Anyone in the project can join a session.** Messages and tool calls record who or which agent made them.
- **Dashboard definitions are versioned.** A report generated from a dashboard records the dashboard version as well as the run, so later edits by the agent do not change what the report showed.
- **Reports are listed in two places.** Under the session or dashboard that produced them, and in a project-wide list.
- **MCP calls carry their context.** Every tool call names the project and the session or dashboard it acts in.

### What a session shows

- **A dashboard can open beside the conversation.** The session's right-hand panel shows a dashboard of the project, and the agent modifies it there, for example to add a metric it has just found. Each change creates a new dashboard version.
- **In-platform conversation is part of the session.** Messages, tool calls and widgets appear in order.
- **Work by an external agent is marked on the widget card.** The card's header names the client that created it, which MCP reports when it connects, and the time. Without this, a session driven from outside would be a row of unexplained widgets.
- **Tools take a short note.** Every tool that creates a widget accepts a one-line reason from the calling agent. The card header shows it, so an externally driven session still reads as a sequence of steps.

### Data sources

A data source is registered in the project once and referenced by source operators. The registration holds the address, the access kind (URL, request, browser or document), credentials if any, and the freshness policy. Changing a policy then applies to every pipeline that reads the source.

## Major classes

&#91;embedded content: major classes · 14 classes in three groups inside a project\]

A UML class diagram with names only; attributes and operations come later. Filled diamonds are composition, open arrows are navigable associations with their multiplicity at the target end, and the hollow triangle is generalization: Operator is abstract and has six kinds. Shaded classes are immutable. A pipeline is not a class of its own: it is an operator together with everything upstream of it.

## Pipelines

A pipeline is a graph of operators that the server plans and runs like a database query, one level up: an operator is a whole analysis action, not a relational primitive. Every tool call adds an operator, so the agent never builds a pipeline separately.

- **Operators return handles, not data.** Each call (load a source, run SQL, run a statistic) returns an operator id plus a small preview. Later calls take operator ids as inputs.
- **Exploration stays free.** The agent can add as many operators as it likes and read the previews. Nothing needs buffering on the agent's side.
- **A widget is created from an operator id only.** The server reads the data from that operator. The agent never passes values into a widget, so it cannot retype or alter a number.
- **The pipeline is the widget's upstream operators.** Walking back from the widget gives the full chain: source, fetch time, SQL, statistic and parameters.

### Materializing and pass-through operators

An operator either stores its output or only its definition, and the choice follows from whether the output can be recomputed exactly.

|  | Materializing | Pass-through |
| --- | --- | --- |
| Stores | A snapshot of its output, with content hash and time | Only its definition |
| Used for | Anything that touches the outside world or a model: API reads, web extraction, PDF parsing, model-based extraction | Deterministic work on earlier outputs: filters, joins, aggregations, most statistics, widget bindings |
| Why | The result can change, costs money, or is not reproducible, so the snapshot is the evidence | The result is a pure function of its inputs, so storing it adds nothing |
| In DuckDB | A table | A view, composed into one query with its neighbours |
| On refresh | Runs again only when asked: a monitor fires, a user requests it, or it expires. This creates a new snapshot version | Recomputes automatically when an upstream snapshot changes |

Materializing has two distinct reasons, and the model should keep them apart:

- **Required.** The operator is not deterministic or has an external cost. Its snapshot is part of the evidence and is never dropped while a widget depends on it.
- **Optional.** The operator is deterministic but slow. Its snapshot is only a cache, and the server may create or drop it freely.

### What carries over from query engines

- **Logical plan versus execution.** The agent builds the operator graph; the server decides how to run it.
- **Pipelining and breakers.** A chain of pass-through operators fuses into a single DuckDB query. A materializing operator is a pipeline breaker.
- **Lineage.** The upstream walk from a widget is its lineage, and the "view pipeline" page is the plan made readable.
- **Refresh.** A new snapshot invalidates everything downstream, as with a materialized view. If the new snapshot has the same content hash, downstream work is skipped.

The analogy stops in two places. Outputs are not always tables: an operator can produce a table, a document, or a result object such as a model fit, so inputs and outputs need types. And there is no cost-based optimiser to write, because the agent is the query author and the plans are small.

### Runs

A run is one execution of a pipeline for a given set of parameters, and its run id is what makes a result addressable later.

- **Snapshots belong to runs.** Each materializing operator records its snapshot under the run that produced it.
- **Runs reuse snapshots.** A later run takes an existing snapshot when the operator's definition and parameters are unchanged and the snapshot is still fresh. Nothing materializes again without a reason.
- **Freshness is a policy on the operator.** Manual, on an interval, or on change when a monitor fires.
- **Run id plus operator id is an address.** Together they name any intermediate result, which is what a link back to the platform opens.
- **Reports pin a run; dashboards follow the latest one.**

### Input operators

An Input operator is a named, typed slot in a pipeline that is bound to another pipeline: inputs are how pipelines are composed into a DAG.

- **What it declares.** A name and a schema: columns, types, time column and grain. Anything bound to it must match, and the check happens at bind time.
- **What it binds to.** Any pipeline, from a single source to a long chain. The Input itself is pass-through.
- **Bindings are run parameters.** A run is defined by its time range plus its bindings, so the same reuse and invalidation rules cover both.
- **Templates need no extra concept.** A pipeline with Inputs is a template; binding them instantiates it.
- **Bound inputs are not marked.** A run that binds an input reports it (`is_scenario`, a historical name), but widgets do not show it: binding composes pipelines and says nothing about whether the numbers are measured. Scenarios as what-ifs were planned and abandoned (2026-11-15) in favour of cases and models.
- **Comparison is composition.** A pipeline can use the same sub-pipeline twice with different bindings, which compares the two in one widget.

Place Inputs only where a pipeline is meant to be composed or swapped. Elsewhere a source stays a plain operator.

### Agent operators

An agent operator turns incoming data into generated text or structured judgement, such as recommendations, so that generated content is part of the pipeline and not written around it.

- **Inputs.** The outputs of other operators, a prompt, a model, and optionally reference documents such as the strategy text.
- **Output.** Structured and typed: for recommendations, a list of items with text, the evidence each rests on (operator ids and row keys), and a scope.
- **Always materializing.** It is not deterministic and it costs money, so its snapshot is evidence. It runs again only when its inputs, prompt or model change.
- **No tools.** It is a function of its inputs. An agent that explores and builds pipelines is the interactive agent, which is a different thing.
- **Small inputs only.** The data goes into the prompt, so inputs must be aggregated results, with a row limit enforced.
- **Numbers are checked.** Any figure in the generated text must appear in the inputs; otherwise the output is rejected. Better still, the text refers to values by reference and the widget fills them in.
- **Labelled as generated.** A recommendation widget shows the model, the prompt and the evidence, and is visually distinct from computed data.

This removes the separate "agent writes the prose" step. A report is a template plus a run, and everything in it that depends on data is a widget.

### Invalidation

Each operator result has an identity made of the operator's definition, its effective parameters and the identities of its inputs. A result is reused when that identity matches and its sources are still fresh.

From above, parameter equality decides reuse, with two refinements:

- **Per operator, not per run.** Only the parameters an operator actually uses count. Changing a dashboard's time range must not invalidate an operator that ignores it.
- **Time ranges split into periods at sources.** Asking for 2015–2024 after 2015–2023 reuses nine stored periods and fetches one.
- **A changed definition is a new operator identity.** Editing SQL or a prompt never overwrites old results, so pinned reports stay intact.

From below, a source's snapshot stops being fresh through one of these:

| Trigger | How it works | Fits |
| --- | --- | --- |
| Time to live | The snapshot expires after a set age | Default for any source |
| Probe | A cheap check for change before a full fetch: a last-updated field, an HTTP validator, or a hash of a small response | Sotkanet, whose indicators carry a data-updated date |
| Push | A monitor webhook marks the source stale | Context.dev monitors |
| Manual | A person or the agent asks for a refresh | Everything |

- **Freshness can differ by period.** Old periods rarely change and can live long. The latest or preliminary period gets a short lifetime.
- **Change propagates by identity, not by a walk.** A new snapshot has a new content hash, so every downstream identity changes. If the fetched content is identical, the hash is too, and nothing downstream runs again. This also stops agent operators from regenerating when the data did not change.
- **A run is a consistent cut.** At its start a run fixes which snapshot version each source uses, so all widgets on a dashboard share one as-of state.
- **Pinned runs keep their snapshots.** Cleanup never removes a snapshot that a report's run refers to.
- **Failure serves the last good snapshot.** A failed refresh keeps the old data, marks it stale on every widget, and raises a data-quality alert.
- **Eager where someone is waiting.** Sources refresh by policy. Downstream work is lazy, except for pipelines that have alert rules, which run on each rule's check interval.

Operator kinds:

1. **Source** (materializing): a local file, an API, or a web page or PDF. Stored with URL, fetch time and content hash.
2. **Extract** (materializing): model-based extraction of rows from a document.
3. **Input** (pass-through): a named, typed slot bound to another pipeline.
4. **Transform** (pass-through): SQL over earlier operators.
5. **Statistic** (pass-through, optionally cached): a named tool with parameters, for example a regional rate comparison with confidence intervals.
6. **Agent** (materializing): generated text or judgement from incoming data and a prompt.
7. **Widget** (pass-through): a display spec bound to one operator's output.

One gap remains: numbers the agent writes into prose. Close it by giving reports an inline single-value widget, so a sentence can show a figure that is still bound to a pipeline.

## Showing widgets on clients

Do both, with the frontend session as the base: keep the workspace on the server and let any agent drive it through the MCP tools.

There is a protocol for the first half of the question. MCP Apps is an official MCP extension: a tool declares a `ui://` resource and the host renders it in a sandboxed iframe inside the conversation. The official docs list Claude (web), Claude Desktop, VS Code GitHub Copilot, Microsoft 365 Copilot, Goose, Postman, MCPJam and Archestra as hosts; ChatGPT is not on that list. Support is negotiated per connection, so a server can fall back to text. A terminal client such as Claude Code cannot render it at all.

That makes the server-side workspace the dependable path:

- The workspace (operators, widgets, reports) lives in the MCP server, not in any client.
- The frontend subscribes to a workspace and renders changes live.
- A local Claude session and the agent inside the frontend call the same tools on the same workspace. Driving the frontend from an external agent then needs nothing extra.
- Every widget tool result returns a text summary and a link to the widget in the frontend.

| Client | How it shows a widget |
| --- | --- |
| Claude Code or another terminal client | Text summary and link; the frontend open beside it updates live |
| Our frontend | Acts as an MCP Apps host itself and renders the same widget bundle; its embedded agent uses the same MCP tools |
| Hosts with MCP Apps | The widget bundle served as a `ui://` resource, shown inline with no extra work |

Two findings from the official docs change the widget design:

- **One widget format everywhere.** A host can be built with the SDK's App Bridge module or the `@mcp-ui/client` React components. If our frontend is such a host, every widget is written once as an MCP App and also works inline in Claude. The "arbitrary widget in an iframe" tier is then the normal case, not an extra.
- **Widgets fetch their own data.** An MCP App can call tools on its server. The tool result that creates a widget carries only the widget id; the widget then asks the server for the data of its operator. The data never passes through the agent.

## Data sources and the PDF question

DuckDB is the one query layer: SQL for tables and full-text search for documents. It reads CSV, Parquet and JSON files and HTTP URLs directly.

A real `context.dev-pdf` driver is not practical this weekend, but a source step gives the same experience and fits the pipeline model better.

- **Why not a driver.** Native DuckDB extensions are written in C++. The Python client registers scalar functions only; its documentation describes no table functions.
- **Source operator (recommended).** `ingest(url)` calls Context.dev Parse, then stores the Markdown in a `documents` table with URL, fetch time, content hash and section. A second operator turns a table in the document into rows.
- **Why materialise.** Each call costs credits, and Context.dev says cached results cost the same as fresh ones. A stored snapshot is also what makes the pipeline reproducible.
- **Driver feel, if wanted.** Register a scalar function so SQL can call `ctx_parse('https://…/file.pdf')`. It would read from the same snapshot cache.
- **Tables inside PDFs.** Parse a Markdown table deterministically where the layout allows. Fall back to schema-shaped extraction otherwise, and mark those rows as model-extracted in the provenance.

Planned sources for the health demo: THL Sotkanet regional indicators, Finnish Cancer Registry statistics, and the three strategy PDFs from the challenge resources. What they publish per region is in the next section.

## Data availability for the health demo

This data validates the platform approach; it will stay incomplete and does not need to be complete. Public regional data covers early detection well and survival partly; time to treatment and stage at diagnosis have no usable public series.

The strategy's third objective is "Ensuring equal and effective cancer care". The table also lists the early-detection indicators from the second objective, because the brief names late detection as a bottleneck.

| Strategy indicator | Target | Public data found | Regional level |
| --- | --- | --- | --- |
| Screening participation (objective 2) | 80% in each wellbeing services county | Sotkanet 3621 breast (1992–2024), 3620 cervical (1991–2024), 6103 colorectal (2022–2024) | County and municipality |
| Stage at diagnosis (objective 2) | At least 70% at stages I–II | Cancer Registry application, 2020–2024, national only. Stage is unknown for 62% of cases (118,276 of 191,622), so the target cannot be measured today | None |
| Five-year survival, poor-prognosis cancers (objective 3) | Nordic level: lung +14, pancreas +6, liver +14 percentage points over 2023 | Cancer Registry application: age-standardised relative survival for every cancer site, 2022–2024, by five collaborative areas and by education level. Sotkanet adds county-level survival for breast (3625) and cervical (3626), 2015–2024 | Collaborative area; county for breast and cervical |
| Cancer mortality (objective 3) | 10% lower than 13,300 deaths a year | Not in Sotkanet by region. Statistics Finland table 13u5 has deaths and crude death rates by cause and county for 1969–2025, including lung, pancreas and liver. Crude rates are distorted by age structure; the Cancer Registry application has age-standardised mortality | Unknown |
| Treatment within target times (objective 3) | THL target times (Ohjaus 21/2016) | No cancer-specific series found. Proxies for all specialities: referrals processed after more than 21 days (5033) and within 3 days (13), 2014–2025 | County |
| Oncology and radiotherapy outpatient visits (context) | None | Sotkanet 2475, 1994–2024 | County and municipality |

- **A first gap is already visible.** Breast screening participation in 2024 ran from 74.3% in the City of Helsinki to 85.6% in North Ostrobothnia, against the 80% target for every county.
- **The minimum requirement is met.** Survival by county is an objective 3 indicator with public data, though only for breast and cervical cancer.
- **The pathway is covered unevenly.** Detection has good data, referral has a proxy that is not cancer-specific, and diagnosis-to-treatment has nothing public. That missing part has to come from mentor interviews or web extraction, and the report must say so.
- **Access is simple.** Sotkanet is an open REST API with no key, and it returns values for all 23 wellbeing services counties.

Findings from the Cancer Registry application, read on 14 November 2026:

- **The stage target cannot be measured.** For 2020–2024 the registry has no stage for 62% of cases. Among cases with a known stage, 30% were localised (22,248 of 73,346).
- **For lung cancer the gap is by education, not by region.** Five-year relative survival in 2022–2024 was 17.1% for people with basic education and 29.4% for those with tertiary education, and the confidence intervals do not overlap (15.8–18.6 against 26.8–32.2).
- **Regional lung survival is flat.** It runs from 19.5% to 21.8% across the five collaborative areas against 20.5% nationally, with overlapping intervals.
- **County-level survival is not published** for the poor-prognosis cancers the strategy targets. Only incidence, and probably mortality, go down to county level; mortality is not yet checked.

### What the challenge resources add

The roadmap confirms that Finland has no cancer-specific monitoring of time to treatment yet; building it is one of the roadmap's own measures.

- **Target times are still to be defined.** Measure 3.1.2 creates national care pathways that set target access times, with the indicator "patients access treatment within target times". Until then there is nothing to measure against.
- **Nordic models are named.** The pathways are to follow Denmark's Kræftpakkeforløb, Sweden's standardiserade vårdförlopp and Norway's Pakkeforløp. Their published waiting times are a possible benchmark and a natural web-extraction source; not yet checked.
- **Pathway indicators are named.** The roadmap lists stage at diagnosis, access times, the share treated with curative intent, and survival.
- **One equity signal is cited.** An unpublished lymphoma study found diagnosis takes twice as long for patients who enter through public health centres as for those using private or occupational care.

The link collection points to these data sources:

| Source | What it offers | Access |
| --- | --- | --- |
| [Cancer Registry statistics application](https://tilastot.syoparekisteri.fi/syovat/) | Incidence, mortality, prevalence and survival, with tables by stage and by education level. Incidence covers all 23 counties, survival covers five collaborative areas, and stage is national only | A Shiny application with no REST API. Its CSV export works from an automated browser session, so a browser-based source operator can read it |
| [Statistics Finland cause-of-death statistics](https://stat.fi/fi/tilasto/ksyyt) | Cancer deaths | Open PxWeb API with no key; table 13u5 confirmed |
| [NORDCAN](https://nordcan.iarc.who.int/en) | Nordic incidence, mortality and survival | Open API at canapi.iarc.who.int with no key. Metadata routes are confirmed; data routes are not yet mapped. Survival is national only, while incidence and mortality also cover five Finnish regions |
| [Kela open data](https://tietotarjotin.fi/tilastodata/2242438/avoin-data) | Medicine reimbursement entitlements | Not yet queried |
| [FICAN quality registers](https://fican.fi/toiminta/arviointi-ja-seuranta/syopien-laaturekisterit/) | Status of cancer quality registers | Not yet read |

The remaining links are strategy pages, research-permit bodies (Findata, FinRegistry) and biobanks, which need permits and are out of reach for a demo.

### Nordic benchmark

All three countries the roadmap names publish how many cancer patients are treated within target times, by region. The Swedish and Danish reports were opened; the Norwegian row is from a search summary.

| Country | Target | Result for 2025 | Published by | Granularity |
| --- | --- | --- | --- | --- |
| Sweden | 80% of patients within the set lead times | 47% nationally, up from 45% in 2024; only acute leukaemia meets the target | [Regional cancer centres](https://cancercentrum.se/download/18.7c07b08019d24db18e31c22a/1774867469204/%C3%85rsapport%20%C3%B6verenskommelse%202025%20J%C3%A4mlik%20och%20effektiv%20cancerv%C3%A5rd%20med%20kortare%20v%C3%A4ntetider_bilaga%201%20SVF.pdf), annual report appendix | Region and pathway, but regional values are in charts, not text |
| Denmark | Share of pathways within the standard time | 77% nationally; regions range from 67% (Zealand) to 81% (Southern Denmark) | [Danish Health Data Authority](https://cdn1.gopublic.dk/sundhedsdatastyrelsen/Media/639168548110422377/monitorering-af-kraeftomraadet-aarsopgoerelse-2025.pdf), annual report | Region, pathway and quarter, as text tables |
| Norway | 70% of pathways within the recommended time | Not yet read | [Norwegian Institute of Public Health](https://www.fhi.no/he/npr/statistikk-npr/pakkeforlop-for-kreft/) | Health trust and cancer type |

- **This gives the demo its missing pathway stage.** Finland cannot yet show diagnosis-to-treatment times, but its three named models can. The comparison itself is evidence for a recommendation.
- **The reports are PDFs.** They are a natural case for the Context.dev parse source, once credits may be spent.
- **Socioeconomic equity has data too.** The Cancer Registry application has incidence, mortality and survival tables by education level, which fits the roadmap's concern about public versus occupational care.

### Nordic comparison

The same analysis runs for all Nordic countries through NORDCAN, which holds comparable incidence, mortality, prevalence and survival for Denmark, Finland, Iceland, Norway and Sweden. Finland has the lowest survival of the four large countries for all three cancers the strategy targets.

Five-year relative survival, 2020–2024, men / women, in percent ([NORDCAN](https://nordcan.iarc.who.int/en), queried 14 November 2026):

| Cancer | Finland | Denmark | Norway | Sweden |
| --- | --- | --- | --- | --- |
| Lung | 17.9 / 30.8 | 28.1 / 37.2 | 30.8 / 38.4 | 31.3 / 38.9 |
| Pancreas | 12.1 / 13.6 | 15.8 / 15.3 | 18.7 / 20.0 | 17.3 / 17.9 |
| Liver | 14.4 / 12.5 | 19.5 / 19.9 | 24.5 / 25.9 | 25.8 / 23.6 |

What the other countries publish compared with Finland; the last three rows are from search summaries only:

| Measure | Finland | Other Nordic countries |
| --- | --- | --- |
| Incidence, mortality, prevalence, survival | NORDCAN and the Cancer Registry application | NORDCAN, comparable across countries |
| Regions within a country | Counties for incidence; five areas for survival | NORDCAN has a few regions per country, for incidence and mortality only |
| Time to treatment | Nothing | Sweden, Denmark and Norway all publish it by region |
| Screening participation by region | Sotkanet, open API | In national reports; no open API found |
| Stage at diagnosis | Unknown for 62% of cases | Norway reports survival by stage; others not checked |
| Survival by education | Cancer Registry application | Not found |

Norway's cancer statistics bank goes down to county and municipality and added survival in May 2026; it offers file downloads but no documented API.

### Source kinds

Importing by URL works for two of the five sources, so a plain URL source is not enough on its own.

| Source kind | How it reads | Covers |
| --- | --- | --- |
| URL | DuckDB reads CSV, JSON or Parquet straight from a stable address | Sotkanet, NORDCAN |
| Request | One HTTP request with a body, returning CSV or JSON | Statistics Finland, which takes a POST query |
| Browser | An automated browser session sets options and takes the export | Cancer Registry application, whose CSV link is tied to a live session |
| Document | Fetch a PDF or page, parse it, then extract tables | Nordic pathway reports, strategy documents |

All four are materializing source operators with the same output contract: a table or document plus address, fetch time and content hash.

### Does the data support the platform approach

Yes for the core, and it exposed three gaps in the model. Live monitoring is only weakly tested by it.

| Platform idea | What the data showed | Verdict |
| --- | --- | --- |
| Source operators with provenance | Five sources needed four access kinds, and one export only exists inside a browser session | Supported |
| Materializing with snapshots | Statistics get revised and one source has a preliminary year | Supported |
| Probing before refetching | Sotkanet indicators carry a data-updated date | Supported |
| Time as a first-class concept | Annual, quarterly, three-year and five-year periods, ending in different years | Supported, with a gap |
| Composition through Inputs | A pipeline built from other pipelines, swappable per run | Supported |
| Agent operator for recommendations | The findings need judgement: an education gap, a Nordic gap, two unmeasurable targets | Supported |
| Dashboards and alerts | Almost everything is annual, so a rule fires at most once a year | Weakly tested |

The three gaps:

- **Periods are intervals, not points.** Survival is published for windows such as 2022–2024 and 2020–2024. A time column with a grain is not enough; a value needs a period start and end, and alignment has to handle overlapping windows.
- **Geography needs the same treatment as time.** The sources use counties, collaborative areas, hospital districts, municipalities, and each country's own regions. Region level and the mapping between levels should be declared on tables, and a join across levels should be an explicit operator.
- **Values carry more than a number.** Survival comes with confidence intervals, small counts are suppressed, and 62% of stage values are unknown. The value model needs an interval, a suppressed flag and a coverage share, and widgets should show them.

For monitoring, a faster series would be a better test: the Danish quarterly pathway data, monthly waiting-time statistics, or web sources through Context.dev.

## OpenUI

Recommendation: leave OpenUI out for now and store report and dashboard layouts as a plain JSON component tree. OpenUI could return later as an optional authoring layer for the in-platform agent.

OpenUI is an open-source generative-UI framework from Thesys. A model writes a compact, streamable language (OpenUI Lang) against a component library you define, and a React renderer draws it as the tokens arrive. Its repository confirms component contracts typed with Zod, custom component libraries, bindings for React, Vue, Svelte and Angular, and an MIT licence. It does not show how a component is declared; that needs the full docs.

- **Where it fits.** The agent composes a report from our registered components: section, callout, recommendation and widget. The widget component accepts only a widget id, so the "only widgets carry data" rule is enforced by the component library itself.
- **Where it does not.** It does not show widgets in other clients (that is MCP Apps), and it does not replace a charting library inside a widget.
- **Alternative.** A plain JSON component tree does the same job with no new dependency, but without streaming. Choose OpenUI if someone on the team already knows it.

Why the design has moved away from it since this section was first written:

- **Layouts are stored, versioned records.** A dashboard version or report version needs one canonical form in the database, with slots, revisions and validation. That form is a JSON tree either way.
- **External agents write layouts through MCP tools.** Tool parameters are JSON schemas. A local Claude session will not emit OpenUI's language unless it is taught the grammar, so JSON is the interchange format regardless.
- **Widgets are MCP Apps in iframes.** OpenUI would only arrange them; it renders none of the data.
- **Generated text comes from agent operators.** The agent no longer streams report prose into the page, which was the case OpenUI's streaming is built for.

What is left for OpenUI is progressive rendering while the in-platform agent drafts a layout. Its output would compile to the same JSON tree, so adding it later changes nothing underneath.

## Reports

A report is a one-time document frozen at a run: a tree of components in which widgets are the only parts that hold data.

- **Two kinds of component.** Static components (headings, fixed text, callouts) come from the template or its author. Everything that depends on data is a widget, including generated text.
- **Templates.** A template is a report with named empty slots, each describing the widget it expects. The agent fills the slots and writes the prose around them.
- **On the fly.** Without a template the agent writes the whole tree from the same components.
- **Link back.** Every widget shows a link to its pipeline on the platform: operators, SQL, sources and fetch times.
- **Sources list.** Generated from the source operators of all widgets in the report, never written by hand.
- **Recommendations.** Produced by an agent operator and shown by a recommendation widget. Each one names the evidence it rests on, so a reader can check it.
- **Export.** A report records its run id and time range, so it always shows the same numbers, and its link opens the pipeline exactly as it ran.

### Versions

A report has a name and any number of versions, numbered as semantic versions. Every version is immutable and records its run, time range and template or dashboard version.

| Level | Proposed meaning | Example |
| --- | --- | --- |
| Major | The structure or the pipelines changed, so numbers are not comparable with the previous version | A new indicator replaces an old one |
| Minor | The same report on a new run or time range | The yearly refresh with 2025 data |
| Patch | Same run and same data; only static text or layout changed | A corrected heading |

The platform can propose the level, because it knows whether the pipelines, the run or only the static parts changed.

First template, for the AstraZeneca demo: headline gap, map by wellbeing services county, care-pathway stage where the gap emerges, trend over time, recommendations, sources. It should be readable in under two minutes, as the brief asks.

## Monitoring dashboards

A dashboard is the live counterpart of a report: the same widgets and pipelines, but following the latest run instead of a pinned one.

|  | Dashboard | Report |
| --- | --- | --- |
| Purpose | Watch indicators over time | State a finding and a recommendation once |
| Data | Latest run; refreshes by each source's freshness policy | Pinned to one run id |
| Time range | A control the viewer changes | Fixed when the report is generated |
| Prose | Little or none | Written by the agent around the widgets |
| Template slots | Advisory: each says what probably belongs there | Each expects a specific widget |
| Link back | To the live pipeline | To the pipeline at its run |

- **Reports come from dashboards.** Generating a report freezes the dashboard's current run and time range, and copies the chosen widgets; generated text comes from agent operators in the same pipelines, so there is no separate writing step. A dashboard template can carry a matching report template.
- **Alerts turn a dashboard into an early-warning system.** Alerts are defined on pipelines and described in the next section. The AstraZeneca brief lists both a monitoring dashboard and an early-warning system as possible solutions.
- **This is also the Context.dev fit.** A dashboard whose sources refresh when a monitor fires reacts to change over time, which a one-time report cannot.

## Alerts

An alert is a rule on a pipeline's output, evaluated on the rule's own check interval. It is not a widget, though a widget can show the same pipeline.

- **Pipeline.** Produces rows, each with a key such as region and indicator.
- **Rule.** Says which rows count as alerting, how severe they are, and what to do.
- **Alert instance.** One per key, with a state: firing since a given run, or resolved. Instances are deduplicated by key, so a region that stays below target alerts once, not on every refresh.
- **Actions.** Notify, call a webhook, or generate a report from a template with the triggering run pinned.
- **Display.** Alerts live in their own feed and as badges on dashboards. A map or table of the same pipeline is an ordinary widget.
- **Trace.** Every alert event carries its run id, so it opens the exact data that triggered it.
- **Dry runs.** A rule can be evaluated on a run with other bindings without notifying anyone, to answer "would this have fired?".
- **Data-quality alerts.** A failed refresh, a schema change or a stale source uses the same mechanism.

### Rules and alert pipelines

The condition lives in the rule, as a formula over the pipeline's output. One measure pipeline can then feed a widget and several alerts.

- **A rule is a formula tree.** Nodes are column references, constants, arithmetic, comparisons, and/or/not, and time functions such as previous period, change over n periods and rolling mean. It is evaluated per key.
- **Time functions use the table's grain.** "Previous period" means the previous year for an annual series and the previous quarter for a quarterly one.
- **Tree builder first.** The interface builds one tree per rule. A graph-based builder that lets rules share sub-expressions can follow; giving sub-expressions ids from the start means that change is to the interface only.
- **Rules compile to SQL.** A formula becomes a filter on the pipeline's output, so evaluating it is one query. Each evaluation records the rule version and the run id, which keeps alerts traceable although the rule sits outside the pipeline.
- **An alert can have its own pipeline.** It runs when the alert fires, with the alerting rows bound to its Input. An agent operator in it can write a summary, which is attached to the alert event and its notification.

Check interval:

- **Each rule sets its own.** A rule on quarterly data can check weekly; a rule on a web source can check every few minutes. "On change" stays available as a value, for sources that push.
- **A check is a run of the measure pipeline.** It follows the normal reuse rules, so a check finds fresh data only as often as the sources allow.
- **Checking more often than the source refreshes is cheap, not useful.** The snapshot is reused, the result identity is unchanged, and the rule is not evaluated again.
- **A rule can demand fresher data.** An optional maximum data age on the rule forces a source refresh when a snapshot is older, overriding the source's own policy for that check.
- **The interval is part of the rule's revision.** Changing it is an edit like any other.

| Part | What it is | Example |
| --- | --- | --- |
| Measure pipeline | Produces rows with a key | Screening participation by county and year |
| Rule | A formula tree over those rows | Value below 80, or down 5 points on the previous period |
| Alert pipeline, optional | Runs on the alerting rows when the rule fires | An agent operator summarises which counties slipped and by how much |

The alert pipeline is an ordinary pipeline: it is pinned to the triggering run and can be opened like any other.

## Time ranges

Nearly all the data is a time series, so the time range is a parameter of the pipeline, not a filter the agent writes into SQL.

- **Two time axes, kept apart.** The data period is which years the values describe. The as-of time is when they were fetched, which is the run. A report pins both.
- **Tables declare their time column and grain.** A period has a start and an end, so multi-year windows such as 2022–2024 fit as well as years and quarters.
- **The range is pushed down to sources.** A source operator fetches only the requested periods, as Sotkanet and Statistics Finland both allow. This is predicate pushdown in the query-engine sense.
- **Snapshots are stored per period.** A refresh then fetches only new or revised periods, and old periods stay untouched.
- **Widgets choose a range mode.** Follow the dashboard's range, show the latest period only, or show full history.
- **Grains never align implicitly.** Combining an annual and a quarterly series needs an explicit alignment operator, visible in the pipeline.
- **Sources end at different times.** Sotkanet's screening data ends in 2024 and Statistics Finland's deaths in 2025. Every widget labels the period it shows, and comparisons use the latest period the sources share.

## Semantic roles

Intervals, geography and uncertainty are handled in both places: the data and its conversions stay in pipelines, and the platform holds only a thin declaration of what the columns mean.

The test for where something belongs: if two independent components must read it the same way, the platform needs to know. If it is one pipeline's logic, it stays in the pipeline.

| Layer | Holds | Examples |
| --- | --- | --- |
| Pipeline columns | The data itself, as ordinary columns | Period start and end, region code, value, lower and upper bound, suppressed flag |
| Platform roles | What those columns mean, declared on a table | Time interval; geography with code system and level; measure with its bounds, suppression and coverage |
| Library operators | The conversions | Align periods, map one region level to another, compute a confidence interval |

The platform needs roles because several components depend on them at once:

- **Widgets.** A map must know the region level, and a chart draws the interval as a band.
- **Rules.** Time functions such as "previous period" need to know what a period is.
- **Pushdown.** The time range can only be pushed to sources if the platform knows the time columns.
- **Inputs.** A swapped-in pipeline is checked for the same level and period shape, not only the same column names.

Two guards follow from roles:

- **Confidence intervals do not survive aggregation.** A transform that aggregates such a measure drops the interval role unless a statistic operator recomputes it. The widget then shows no band instead of a wrong one.
- **Suppression propagates.** Widgets draw suppressed values as gaps, and rules skip them.

Region mapping tables and boundary shapes are reference data, registered as project data sources.

### Operators declare their output schema

Every operator states its output schema, roles included. Where the schema follows deterministically from the inputs and parameters, the operator derives it; where it does not, whoever creates the operator must declare it.

| Operator | Columns and types | Roles |
| --- | --- | --- |
| Source | Declared on the data source registration | Declared |
| Extract | Declared; the extraction schema is the declaration | Declared |
| Input | Declared; it is the slot's contract | Declared |
| Library operators: align periods, map region, statistics | Derived | Derived |
| Transform (SQL) | Derived by asking DuckDB to describe the query | Declared |
| Agent | Declared as its output schema | Declared |
| Widget | No output; it declares the roles it requires of its input | Not applicable |

- **The schema is known before anything runs.** A pipeline can be checked when it is built: an Input binding, a widget's required roles and a rule's time functions are all verified against declared schemas, without fetching data.
- **Declarations are validated twice.** At build time against the derived columns: the named columns must exist and have fitting types. At run time against the actual output: a mismatch fails the run.
- **SQL roles are declared, not guessed.** The columns of a query are certain; what they mean after an arbitrary query is not. Derivation for simple cases, such as a plain filter, can be added later without changing the contract.

## Storage

Use a relational database for definitions and DuckDB only for analysis data.

- **Why relational.** The model is references all the way down: project, session, widget, operator, run, snapshot, report version. It needs foreign keys, transactions and queries across those links, such as "which reports depend on this source".
- **Where documents fit.** Widget specs, operator parameters, rule trees and report trees are nested and change shape often. They go in JSON columns of the same database, which gives the flexibility of a document store without giving up the links.
- **Why not DuckDB for definitions.** It is built for analytical queries with one writer, not for many small concurrent writes.
- **Most records are immutable.** Operators, snapshots, runs, report versions and dashboard versions are only ever added, so they need no locking.
- **Optimistic locking on the mutable few.** A dashboard's current version, a session, an alert rule and a data source registration each carry a revision. An MCP read returns it and an MCP write must send it back. On a mismatch the write is refused with the current state, and the agent reads again before retrying.
- **This is the same shape as version control.** Immutable objects plus a few named pointers that move by compare-and-swap.

The revision check matters most on dashboards, where a person in the frontend and an agent over MCP can edit at the same time.

## Tech stack

No users or authentication for now.

| Area | Choice | Note |
| --- | --- | --- |
| Backend language and layout | Python, hexagonal: core models, ports, services; adapters; entrypoints; one composition root | tach checks the module boundaries in lint |
| Dependency injection | dishka | One composition root wires every port |
| Definitions database | PostgreSQL through SQLAlchemy 2 with psycopg 3, migrations with Alembic | SQLAlchemy's version counter gives the optimistic locking directly |
| Analysis data | DuckDB behind a custom port, with snapshots stored as Parquet files | See the DuckDB note below |
| HTTP API | FastAPI | REST for the frontend, plus the event stream |
| MCP | FastMCP, mounted into the FastAPI app | It supports MCP Apps natively: a tool points at a `ui://` resource |
| Background work | taskiq with Valkey: one worker, one scheduler | Runs, source refreshes, alert checks on their intervals, agent operators |
| Live updates | Server-sent events from FastAPI, fed by Valkey publish and subscribe | No FastStream; see below |
| Frontend | React, Vite, TanStack Router and TanStack Query, Tailwind, shadcn | A single-page app behind the gateway |
| Monorepo | moon, with mise pinning tool versions, uv and pnpm workspaces | `services/backend` and `services/frontend` |
| Images and CI | GitHub Actions builds and pushes to `ghcr.io/benni-tec/ada/<service>` | Tagged `sha-<commit>` and `latest` |

### Decisions that need a reason

- **No FastStream.** It is for messaging between services over a broker, not for pushing to browsers. The frontend needs a one-way stream, which server-sent events cover. The worker publishes an event to Valkey, the API process forwards it to the open streams, and TanStack Query invalidates or patches what changed. Valkey is needed for taskiq anyway.
- **Parquet snapshots instead of one DuckDB file.** A DuckDB file accepts one writing process, but the API and the worker both need the data. Snapshots are immutable and content-addressed already, so each becomes a Parquet file named by its hash on a shared volume. Every process queries them with its own in-memory DuckDB, and pass-through operators are queries over those files. This removes the single-writer problem and moves to object storage later without a redesign.
- **A gateway stays.** One nginx in front gives a single origin for the frontend, the API, the event stream and the MCP endpoint.
- **Upstream images for infrastructure.** Plain PostgreSQL and Valkey images, so only backend, frontend and gateway are built.
- **Widgets are a separate build.** Each widget is a self-contained HTML bundle served by the backend as a `ui://` resource, so the same bundle works in our frontend and in Claude. They are built in a third project, services/widgets, and the backend image copies the build output.
- **A browser in the worker.** The browser source kind needs Playwright, which makes the worker image heavy. A separate browser-worker image keeps the API image small.

### Compose files and moon tasks

| File or task | What it does |
| --- | --- |
| `docker-compose.infra.yml` | PostgreSQL and Valkey only, with ports open to the host for local debugging |
| `docker-compose.yml` | The full stack: includes the infra file and adds migrate, backend, worker, scheduler, frontend and gateway. Deployment variants come later |
| `.env` at the root | The single `VERSION` line that every image tag in the compose files reads |
| `moon run root:infra` | Starts the infrastructure |
| `moon run root:up`, `root:down`, `root:logs`, `root:pull` | Runs, stops, follows and updates the full stack |
| `moon run :dev` | Backend, worker, scheduler and frontend from source with reload, against the infrastructure |
| `moon run :build`, `:image` | Builds the frontend, and builds every image with the tags CI uses |
| `moon run :lint`, `:test`, `:typecheck`, `:format` | The checks CI runs |

### Open points

Settled:

- **VERSION defaults to latest.** A `root:pin` task writes the current commit hash into `.env` when a reproducible deploy is wanted. CI never commits back.
- **The code lives in this working directory**, with the private `benni-tec/ada` repository as its remote.
- **Widgets are a third project**, `services/widgets`, next to backend and frontend.

Still open:

- **Where the in-platform agent runs.** The proposal is a taskiq worker that calls the model and uses the same services the MCP tools use, with its messages streamed to the frontend over the event stream.
- **Chart and map libraries for widgets.** A declarative chart spec that an agent can write, and a map for regions, are still to be chosen.
- **Typed API client.** Generating the TypeScript client from FastAPI's OpenAPI schema would keep both sides in step.

API keys for the model and for Context.dev only ever come from the environment, never from the repository.

## Risks and open questions

Everything above is in scope. Three checks are done; the rest is open.

- [x] Sotkanet indicators per region checked.
- [x] MCP Apps host support confirmed in the official docs.
- [x] DuckDB Python client confirmed as scalar functions only.
- [x] Roadmap PDF and link collection from the challenge resources read.
- [x] Statistics Finland cause-of-death table by county confirmed.
- [x] Swedish and Danish pathway reports opened.
- [x] Cancer Registry statistics application opened: stage, survival by area and by education read.
- [x] NORDCAN survival route mapped and the Nordic comparison pulled.
- [x] Alert condition decided: a formula tree in the rule.
- [ ] Define the role vocabulary: time interval, geography, and measure with bounds, suppression and coverage.
- [ ] Provide region mapping tables and boundary shapes per level as project reference data.
- [ ] Specify the build-time schema check: exactly what is verified before a pipeline runs.
- [ ] Confirm what major, minor and patch mean for report versions.
- [ ] Define the function set for rule formulas, especially the time functions.
- [ ] Decide the premade widget set: map, pathway, single value, source card, declarative chart.
- [ ] Confirm leaving OpenUI out in favour of a plain JSON component tree.
- [ ] Ask the AstraZeneca mentors whether any Finnish time-to-treatment data exists, and validate the recommendation logic with them.

Further data pulls are optional, since the data only validates the approach: Norwegian pathway figures, Sweden's regional values, and NORDCAN's incidence and mortality routes.

## Sources

All pages below were opened except the Exa and Cala entries, which are search-result summaries.

- [Context.dev documentation](https://docs.context.dev/)
- [MCP Apps proposal, SEP-1865](https://modelcontextprotocol.io/seps/1865-mcp-apps-interactive-user-interfaces-for-mcp)
- [MCP Apps announcement](https://blog.modelcontextprotocol.io/posts/2025-11-21-mcp-apps/)
- [OpenUI repository README](https://cdn.jsdelivr.net/gh/thesysdev/openui@main/README.md)
- [Exa Websets overview](https://exa.ai/docs/websets/overview)
- [Cala integration notes at LangChain](https://docs.langchain.com/oss/javascript/integrations/providers/cala)
- Challenge briefs: the Equal Care Across Finland, The Web Is Your Real-Time Database, Best Use of Context.dev, The Internet Butler and Make Unicorns Real tabs in this doc

* [MCP Apps documentation](https://modelcontextprotocol.io/docs/extensions/apps) and [client support matrix](https://modelcontextprotocol.io/extensions/client-matrix.md)
* [DuckDB Python function API](https://duckdb.org/docs/2.0/clients/python/function.html)
* [OpenUI repository](https://github.com/thesysdev/openui)
* [National Cancer Strategy 2026–2035, English PDF](https://stm.fi/documents/1271139/1329769/National_Cancer_Strategy_2026-2035_Finland.pdf/a29aa994-91bb-2bcd-e90e-a3d3fde32b90?t=1770968783502), from the [ministry's strategy page](https://stm.fi/en/national-cancer-strategy)
* [Sotkanet indicator catalogue](https://sotkanet.fi/rest/1.1/indicators), queried on 14 November 2026

- Challenge resources: the implementation roadmap 2026–2031 and the link collection, both from the Equal Care Across Finland brief
