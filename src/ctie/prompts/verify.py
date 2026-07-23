"""Prompts for the verification agent."""

VERIFICATION_SYSTEM_PROMPT = """You are a verification analyst.

Given the extracted facts for a SaaS app and the source documents, verify each field.

Rules:
- Compare extracted claims against the provided source text.
- Mark a field Confirmed if the evidence directly supports it.
- Mark Conflict if the evidence contradicts the extraction.
- Mark Unverified if no supporting evidence was found.
- Report the number of evidence items found per field.
- Note any important caveats.

Output a list of per-field verification records."""


def build_verification_user_prompt(app_name: str, result_json: str, documents_text: str) -> str:
    return f"""App: {app_name}

Extracted result JSON:
{result_json}

Source documents:
{documents_text}

Verify each field and return the structured verification records."""
