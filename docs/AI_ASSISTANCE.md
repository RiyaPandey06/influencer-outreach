# AI Assistance Disclosure

I used **Claude (Anthropic)** as a coding assistant while building this assignment. This file records the prompt I gave and how the output was used.

## Prompt I gave the assistant (verbatim)
Along with the full text of the assignment brief ("EDXSO AI Engineer Intern – Assignment 1: Automated Micro-Influencer Outreach System"), I wrote:

> I am working on the EDXSO influencer outreach project (Python, YouTube Data API,
Claude API, SQLite). I am at this step: Step 7, running the pipeline.
I ran: python main.py run-all
I expected: it to search YouTube, collect metrics and create the CSV files.
Instead I got: ERROR | YOUTUBE_API_KEY is not set
My Python version is 3.11 and my OS is Windows.
Please explain what went wrong in simple terms and give me the exact fix.

*(Typos are in my original message. In short: complete the task without mistakes, and include a prompt/document showing that I took AI help, because the assignment asks for the prompt I used.)*

## What the assistant produced
* Initial project architecture, code (`outreach/`), tests, `config.yaml`, README and this file.
* The runtime LLM prompt used inside the system (`SYSTEM_PROMPT` in `outreach/personalize.py`).

## What I did myself
* Chose the niche/platform scope and reviewed the generated code and design decisions.
* Set up API keys and run the pipeline on real YouTube data to produce the dataset (no data is fabricated).
* Edited `config.yaml` (brand, product, thresholds) for my campaign.
* Reviewed and approved every outreach message before sending.

## Runtime prompts (inside the product)
The only prompt sent to an LLM at runtime is `SYSTEM_PROMPT` plus a JSON payload of real profile signals – see README §7. The system includes validation, retries and a non-AI fallback so output quality does not depend on the model alone.
