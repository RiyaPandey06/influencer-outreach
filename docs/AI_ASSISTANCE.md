# AI Assistance Disclosure

I used **Claude (Anthropic)** as a coding assistant while building this assignment. This file records the prompt I gave and how the output was used.

## Prompt I gave the assistant (verbatim)
Along with the full text of the assignment brief ("EDXSO AI Engineer Intern – Assignment 1: Automated Micro-Influencer Outreach System"), I wrote:

> complete thi tak and pleae dont make any mitake and add ome other prompt hich ho i have taken your help here they are aking for my prompt that i have given you

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
