# AI News Audit: How AI Models Use and Distribute Canadian Journalism

**Replication materials for the MEO Ecosystem Brief, February 2026**

Aengus Bridgman and Taylor Owen — Media Ecosystem Observatory, McGill University

## Overview

This repository contains the data, analysis code, and manuscript source for the MEO brief auditing how AI companies use and distribute Canadian journalism. The brief examines three stages of the AI-journalism value chain: ingestion of news content into training data, generation of derivative content, and distribution that substitutes for visiting news sources.

**Track 1** (citation audit): 2,267 Canadian news stories (1,511 English + 756 French) x 8 models (4 economy + 4 flagship) = 18,135 responses, queried without web search.

**Track 2** (content substitution): 140 articles x 4 economy models x 3 framings x 2 citation conditions = 3,360 probes, queried with web search enabled.

## Rendering the brief

### Requirements

- **R** (>= 4.4) with packages: `tidyverse`, `jsonlite`, `scales`, `ggimage`, `magick`, `grid`, `packcircles`, `cowplot`, `ggrepel`, `rmarkdown`
- **XeLaTeX** (TeX Live 2025+) with Poppins font installed
- **Pandoc** (>= 3.0)

### Build

```bash
# Install R packages (if needed)
Rscript -e 'install.packages(c("tidyverse", "jsonlite", "scales", "ggimage", "magick", "grid", "packcircles", "cowplot", "ggrepel", "rmarkdown"))'

# Render PDF
Rscript -e 'rmarkdown::render("brief.Rmd")'
```

This reads all data from `data/`, generates all figures inline, and produces `brief.pdf`.

### Re-running data collection (optional)

Data collection requires API keys for OpenAI, Anthropic, Google, and xAI. Set them in a `.env` file:

```
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
GOOGLE_API_KEY=...
XAI_API_KEY=...
```

Then:

```bash
uv sync
# Track 1: citation audit
uv run python scripts/run_track1.py
uv run python scripts/code_track1.py
# Track 2: content substitution probe
uv run python scripts/run_track2_probes.py
uv run python scripts/code_responses.py
```

## Repository structure

```
.
├── brief.Rmd                  # Manuscript source (R Markdown -> PDF via XeLaTeX)
├── template.tex               # LaTeX template (MEO Ecosystem Brief format)
├── fullwidth-figures.lua       # Pandoc Lua filter for figure layout
├── pyproject.toml              # Python dependencies
│
├── data/
│   ├── track1_coded.jsonl              # Track 1 economy coded responses (EN)
│   ├── track1_flagship_coded.jsonl     # Track 1 flagship coded responses (EN)
│   ├── track1_coded_gpt_fr.jsonl       # Track 1 economy coded responses (FR)
│   ├── track1_flagship_coded_gpt_fr.jsonl  # Track 1 flagship coded (FR)
│   ├── track1_prompts.jsonl            # Track 1 story metadata (EN)
│   ├── track1_prompts_fr.jsonl         # Track 1 story metadata (FR)
│   ├── track1_coded_qwen*.jsonl        # Intercoder reliability (Qwen alternative)
│   ├── track2_coded.csv                # Track 2 coded responses (deterministic + LLM)
│   ├── track2_deterministic.csv        # Track 2 deterministic coding (n-grams, URLs)
│   ├── track2_responses.jsonl          # Track 2 raw API responses (N=3,360)
│   ├── track2_articles.jsonl           # Track 2 article corpus (140 articles)
│   ├── track2_flagship_pilot.csv       # Flagship robustness check (407 responses)
│   ├── intercoder_reliability.csv      # Intercoder reliability summary
│   ├── outlet_readership.csv           # SimilarWeb readership data
│   ├── coding_sheets/                  # LLM coding prompts and schemas
│   ├── coding_schema.md               # Coding dimension definitions
│   └── DATA_PIPELINE.md               # Data pipeline documentation
│
├── analysis/
│   ├── meo_theme.R                    # MEO ggplot2 theme
│   └── figures/logos/                 # Agent logo assets
│
├── scripts/                           # Python data collection & coding scripts
│   ├── run_track1.py                  # Track 1 data collection
│   ├── run_track2_probes.py           # Track 2 data collection
│   ├── code_track1.py                 # Track 1 LLM coding
│   ├── code_responses.py             # Track 2 LLM coding
│   ├── intercoder_reliability.py      # Intercoder reliability analysis
│   └── ...
│
├── prompts/                           # Standardized prompts sent to AI agents
└── images/                            # Cover and section images
```

## Data

All data needed to reproduce the brief is included in this repository. The full data pipeline is documented in `data/DATA_PIPELINE.md` and `data/coding_schema.md`.

Raw AI agent responses are included for Track 2. Track 1 raw responses are available from the authors on request (the coded extractions used in the analysis are included).

## Citation

> Bridgman, A., & Owen, T. (2026). *AI News Audit: How AI Models Use and Distribute Canadian Journalism*. Media Ecosystem Observatory Ecosystem Brief.

## License

Code is released under the [MIT License](LICENSE). Data and manuscript content are released under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

## Contact

Media Ecosystem Observatory — McGill University
aengus.bridgman@mcgill.ca
