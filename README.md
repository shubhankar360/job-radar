# job-radar

**Find remote jobs you can actually get, rank them with reasons, and tailor a CV that only ever says true things.**

Most "remote" postings are remote-within-a-country. Applying from elsewhere ends at the
location question, and an applicant outside the US and EU wastes most of their week on
roles that were never open to them. job-radar pulls ~12,000 postings a run from nine
sources, keeps the ones a candidate in *their* country can legally be hired for, ranks
them with an itemised score, and builds a tailored application pack for the best ones:
CV (PDF, held to two pages), short cover letter, and a sheet of form answers.

It does not submit applications. That stays a human decision, for reasons below.

```
$ python -m jobradar fetch
  himalayas       577 jobs
  remotive        51 jobs
  remoteok        99 jobs
  jobicy          142 jobs
  weworkremotely  78 jobs
  hn              185 jobs
  greenhouse      6825 jobs     (54 company boards)
  ashby           4370 jobs     (79 company boards)
  lever           196 jobs
12523 postings (12444 new) · 197 requests

$ python -m jobradar rank
  1.  98.0  Frontend Developer - Fully Remote | Upto $85/hr   mercor        $159,800  yes   2d
  2.  86.0  Full Stack Engineer - Fully Remote | Upto $130/hr mercor        $244,400  yes   3d
  3.  85.0  Revenue Operations and AI Systems Engineer        Datahash             —  yes   2d
  ...
  9.  77.0  AI agent engineer                                 Sticker Mule  $250,000  yes  19d
  ...
601 ranked; filtered out: 7252 title outside target roles, 2065 not eligible,
122 manager-level title, 17 director-level title, 9 exec-level title, 1 already applied
```

Of 12,523 postings in the first real run, **2,065 that matched the target roles were not
open to a candidate in India**. That is the number this tool exists for.

## How it decides

### 1. Eligibility is a verdict with a reason

`eligibility.assess()` returns `yes`, `likely`, `relocate` or `no`, and always says why:
"open to APJ", "restricted to United States", "timezone band covers the candidate",
"based in Dubai; sponsorship offered". Rules that matter:

- **An empty location list means nothing**, except on boards that document it as
  worldwide (Himalayas does; the source sets `worldwide=True` explicitly rather than
  leaving the ambiguity to downstream code).
- **EMEA does not include India.** Region words expand to member countries
  conservatively; "Remote, EMEA" roles are run from European payroll and screen on it.
- **Work-authorisation sentences override a vague "Remote".** "Must be authorized to work
  in the US" turns `likely` into `no`.
- **Timezone bands are parsed** ("UTC+3 to UTC+8") and checked against the candidate's
  offset.
- **Relocation is its own verdict.** UK and UAE employers sponsor visas; that is a real
  path, scored below remote because it is slower and riskier.

### 2. The score is a sum of named, bounded parts

Every part leaves a reason string, and a test asserts the reasons add up to the score.
A ranking you cannot explain is one you cannot fix.

| Part | Range | Notes |
| --- | --- | --- |
| Role fit | 16 – 30 | title matched against the profile's role families |
| Skills named | 0 – 30 | weighted skills the candidate has that the posting mentions |
| Gaps | 0 – −12 | technologies asked for that the profile lacks |
| Level | −28 – +10 | from the title; manager/director/exec titles are excluded |
| Years asked | −20 – +5 | the *largest* "N+ years" in the text, ignoring company ages |
| Pay | −10 – +20 | normalised to annual USD; a $200k+ floor on a "mid" title is read as a senior hire (−12) |
| Freshness | −15 – +10 | plus −5 when Greenhouse's `first_published` shows it open 4+ months |
| Eligibility | −18 – +8 | relocation −18; on-site in another city −6 |
| Language | 0 / −15 | a German-language posting wants German in the interview |

### 3. History turns a list into a judgement

Everything is kept in SQLite, so each run knows what came before:

- **Reposts** — the same company + title under a new id *on the same board* (the same
  role on two boards is syndication, not a repost). Two or more is flagged: a role that
  is not being filled, or not real.
- **Company velocity** — roles a company opened in 30 days. Budget shows up as hiring.
- **Your applications** — never re-apply, and enforce per-company caps (some employers
  reject a fourth application in six months outright).

### 4. Tailoring selects; it never writes

`tailor()` picks the headline and summary for the role family, orders bullets by
relevance to *this* posting, and moves the skills it names to the front of their lines.
Every sentence in the output exists verbatim in `profile.json` —
`test_tailored_cv_only_contains_profile_sentences` enforces it. What the posting asks for
and the profile lacks is reported as a gap, never inserted. Named technologies weigh more
than themes ("product", "customer"), because themes appear in almost every posting and
would otherwise decide the order.

The CV is rendered by headless Chrome and re-rendered with the least relevant bullet
removed until it fits two pages.

## Why it stops before "submit"

- **Some employers ban AI-written answers**, sometimes only on the live form. The engine
  flags them (from the posting text and a known list) and generates no letter for them.
- **ATSs add human checks** — Greenhouse emails an 8-character code on submit.
- **Volume is the wrong lever.** The shortlisting problem for a candidate outside the
  US/EU is eligibility and relevance, which is what this tool fixes. A thousand untargeted
  applications mostly hit the same location question a thousand times.

## Use

```bash
python -m venv .venv && .venv/bin/pip install pytest   # no runtime dependencies
export JOBRADAR_HOME=~/.jobradar
mkdir -p $JOBRADAR_HOME && cp examples/profile.example.json $JOBRADAR_HOME/profile.json
# edit profile.json — your facts only; add config.json with sources (see below)

python -m jobradar fetch                 # ~9 min cold, cached for 6 h
python -m jobradar rank --top 30
python -m jobradar prepare --top 10      # application packs under $JOBRADAR_HOME/applications/
python -m jobradar serve                 # dashboard with working "applied / skip" buttons
python -m jobradar log "Acme" "AI Engineer" applied   # applied somewhere else
python -m jobradar daily                 # all of the above, for cron/launchd
```

`config.json` lists sources and company boards:

```json
{"sources": {
  "himalayas": {"country": "India", "pages": 3, "queries": ["ai engineer", "llm", "python developer"]},
  "greenhouse": {"boards": [{"slug": "gitlab", "name": "GitLab"}]},
  "ashby": {"boards": [{"slug": "elevenlabs", "name": "ElevenLabs"}]},
  "lever": {"boards": [{"slug": "toptal", "name": "Toptal"}]},
  "hn": {}, "remotive": {}, "remoteok": {}, "jobicy": {}, "weworkremotely": {}
}}
```

## Tests

```bash
.venv/bin/python -m pytest -q     # 67 tests, offline, < 1 s
```

Sources are tested against small synthetic payloads in the shape each API returns, so a
breaking change in a parser fails here rather than silently emptying a board.

## Layout

```
jobradar/
  sources/      himalayas, remotive, remoteok, jobicy, weworkremotely (boards.py),
                greenhouse, ashby, lever (ats.py), Hacker News "Who is hiring" (hn.py)
  eligibility   can a candidate in country X be hired for this?
  score         itemised ranking          seniority  level + years from text
  salary        any wording → annual USD  vocab      technology vocabulary for gaps
  store         SQLite: jobs, runs, applications, history signals
  rank          dedupe across boards, score, apply history
  tailor        evidence-constrained selection     render  CV/letter/answers → HTML/PDF
  dashboard     single-file UI + local server for status updates
```

Standard library only at runtime. Python 3.10+.

## Licence

MIT
