"""AI-powered translation using OpenAI with structured Pydantic responses."""

import logging

from pydantic import BaseModel, field_validator

from config import CONFIG
from openai import openai_completion

logger = logging.getLogger(__name__)


def _sanitize(text: str) -> str:
    """Remove characters that break Telegram MD or Anki HTML."""
    return text.translate(str.maketrans("", "", "*_`[]<>&"))


class GermanVerbForms(BaseModel):
    """German verb conjugation forms (Präteritum and Perfekt)."""

    praeteritum: str
    perfekt: str


class TranslationContext(BaseModel):
    """A single meaning/context for a translated word."""

    text: str
    type: str
    label: str
    article: str | None
    plural: str | None
    verb_forms: GermanVerbForms | None
    translations: list[str]
    example: str

    @field_validator("text", "type", "label", "example")
    @classmethod
    def validate_non_empty_str(cls, v: str) -> str:
        """Validate that string fields are not empty."""
        if not v or not v.strip():
            raise ValueError("Field cannot be empty")
        return v

    @field_validator("translations")
    @classmethod
    def validate_non_empty_list(cls, v: list[str]) -> list[str]:
        """Validate that translations list is not empty and items are not empty."""
        if not v:
            raise ValueError("Translations list cannot be empty")
        if any(not t or not t.strip() for t in v):
            raise ValueError("Translation items cannot be empty")
        return v


class AiTranslatorResponse(BaseModel):
    """Structured response from the AI translator."""

    contexts: list[TranslationContext]


class Translation(BaseModel):
    """Complete translation result with original request and AI response."""

    request: str
    response: AiTranslatorResponse


TRANSLATION_PROMPT_TEMPLATE = """
You are a language learning assistant helping create flashcards. Analyze the following {source} word or small phrase and translate it to {target}, identifying its DISTINCT meanings/contexts.

Word/Phrase: "{request}"

CRITICAL: Many words have MULTIPLE distinct meanings or types, that are used in different situations. For example:
- German word "auskommen" can mean "to manage financially" OR "to get along with someone"
- German word "schloss" can mean "castle" OR "lock"
- German word "macht" can be a noun meaning "power" or "strength", and a verb meaning "to make" or "to cause" in third person
- English word "stoop" can mean "to bend forward" OR "a front porch/steps"
- English word "pound" can mean "a unit of weight" OR "to hit repeatedly" OR "British currency"

Your task:
1. Correct spelling mistakes in the word, and convert it to infinitive if it is a verb (e.g., German "machen"). Only use this form from now on.
2. Think carefully about the different ways this word is commonly used
3. Identify up to 3 DISTINCT common contexts/meanings, sorted by frequency of use, skip obscure, niche or rare usages, or very similar meanings
4. If the word truly has only one commonly used meaning, provide just one context
5. If the word has MULTIPLE meanings, you MUST provide separate contexts for each

Provide a JSON response with this exact structure:
{{{{
  "contexts": [
    {{{{
      "text": "the original word or phrase with correct spelling",
      "type": "noun/verb/adjective/adverb/etc.",
      "label": "vague category hint (e.g., 'financial', 'social', 'physical', 'building', 'mechanism')",
      "article": "der/die/das for German nouns, null otherwise",
      "plural": "plural of the original word if it is a simple noun, null otherwise",
      "verb_forms": {{{{
        "praeteritum": "past form (e.g., machte)",
        "perfekt": "perfect form (e.g., hat gemacht, ist gegangen)"
      }}}} OR null if not a German verb,
      "translations": ["translation 1 in {target}", "translation N in {target}"],
      "example": "One example sentence in {source} that clearly demonstrates THIS SPECIFIC meaning"
    }}}}
  ]
}}}}

Formatting rules:
- text: the original word or phrase with correct spelling, if it is a single word German verb - use infinitive form. If it is a single noun - make sure there is no article
- type: noun, verb, adjective, adverb, preposition, conjunction, etc
- label: Use vague category hints like "financial", "social", "physical", "building", "mechanism"). AVOID overly specific labels that spoil the answer (bad: "manage money", "get along")
- For German nouns: always include article (der/die/das), for other languages set to null
- For German verbs: always include verb_forms with praeteritum and perfekt, for other languages set to null
- plural: plural of the original word, if original word is a simple noun, if it is not a single word noun then set to null
- translations: Provide at least one {target} translation that fit THIS SPECIFIC context. Don't provide second translation if it is obscure or redundant
- example: Must demonstrate THIS SPECIFIC meaning, not other meanings

Return valid JSON only, no additional text, no MD formatting.
"""


def translate_ai(request: str) -> Translation:
    """Translate a word/phrase using AI and return structured translation data."""
    logger.info("Translating: %s", request)

    prompt = TRANSLATION_PROMPT_TEMPLATE.format(
        source=CONFIG.source_language,
        target=CONFIG.target_language,
        request=request,
    )

    result = openai_completion(prompt, system="")
    response = AiTranslatorResponse.model_validate_json(result)

    # Sanitize model output to prevent breaking Telegram MD / Anki HTML
    for ctx in response.contexts:
        ctx.text = _sanitize(ctx.text)
        ctx.type = _sanitize(ctx.type)
        ctx.label = _sanitize(ctx.label)
        ctx.example = _sanitize(ctx.example)
        ctx.translations = [_sanitize(t) for t in ctx.translations]
        if ctx.article:
            ctx.article = _sanitize(ctx.article)
        if ctx.plural:
            ctx.plural = _sanitize(ctx.plural)
        if ctx.verb_forms:
            ctx.verb_forms.praeteritum = _sanitize(ctx.verb_forms.praeteritum)
            ctx.verb_forms.perfekt = _sanitize(ctx.verb_forms.perfekt)

    translation = Translation(request=request, response=response)

    logger.info(
        "Translation complete: %s -> %d context(s)",
        request,
        len(translation.response.contexts),
    )
    return translation
