"""
Query Expansion Service
Generates multiple query variants to catch more relevant documents
"""
import logging
from typing import List
from app.services.llm import call_llm

logger = logging.getLogger(__name__)


class QueryExpansionService:
    """Service for expanding user queries into multiple variants"""

    @staticmethod
    def expand_query(
        user_query: str,
        max_variants: int = 4,
        llm_provider: str = "ollama"
    ) -> List[str]:
        """
        Generate alternative phrasings of a query.

        When a user asks "What's the main finding?", this will generate:
        - "What are the primary conclusions?"
        - "What are the key results?"
        - "What are the most important discoveries?"
        - etc.

        This catches different phrasings in the source documents.

        Args:
            user_query: Original user question
            max_variants: Number of variants to generate (including original)
            llm_provider: Which LLM to use

        Returns:
            List of query variants (including original)
        """

        if not user_query or len(user_query.strip()) < 3:
            logger.warning("Query too short, returning as-is")
            return [user_query]

        # For very short queries, don't expand
        if len(user_query.split()) < 3:
            logger.info(f"Short query, returning original: {user_query}")
            return [user_query]

        try:
            # Build prompt for LLM
            prompt = f"""You are a search expert. Given a user question, generate {max_variants - 1} alternative ways 
to phrase the SAME question that might catch different phrasings in documents.

IMPORTANT RULES:
1. Generate ONLY {max_variants - 1} alternative questions
2. Each must be a valid question (ends with ?)
3. Keep them semantically similar but worded differently
4. Capture different ways the concept might be expressed
5. Return ONLY the questions, one per line
6. Do NOT number them or add explanations

Original question: "{user_query}"

Alternative phrasings:"""

            # Call LLM
            response = call_llm(
                prompt,
                provider=llm_provider,
                max_tokens=300,
                temperature=0.5
            )

            # Parse response
            variants = response.strip().split('\n')
            variants = [v.strip() for v in variants if v.strip() and '?' in v][:max_variants - 1]

            # Ensure we have valid variants
            if not variants:
                logger.warning("LLM didn't generate valid variants, returning original")
                return [user_query]

            # Add original query first
            all_variants = [user_query] + variants

            logger.info(f"Generated {len(all_variants)} query variants")
            return all_variants[:max_variants]

        except Exception as e:
            logger.error(f"Error expanding query: {e}")
            # Fallback: return original query
            return [user_query]

    @staticmethod
    def expand_query_simple(
        user_query: str,
        max_variants: int = 3
    ) -> List[str]:
        """
        Simple query expansion without LLM (rule-based).

        Generates basic variants by:
        - Removing question words (what, how, why)
        - Adding synonyms
        - Different phrasing patterns

        This is faster and doesn't require LLM but less creative.

        Args:
            user_query: Original user question
            max_variants: Number of variants to generate

        Returns:
            List of query variants
        """
        variants = [user_query]

        # Simple heuristics
        query_lower = user_query.lower()

        # Variant 1: Remove "what is/are"
        if query_lower.startswith("what is "):
            variant = query_lower[8:].strip()
            if variant:
                variants.append(variant)

        # Variant 2: Remove "how do/can"
        if query_lower.startswith("how do ") or query_lower.startswith("how can "):
            parts = query_lower.split(" ", 2)
            if len(parts) > 2:
                variants.append(parts[2].strip())

        # Variant 3: Remove "why"
        if query_lower.startswith("why "):
            variant = query_lower[4:].strip()
            if variant:
                variants.append(variant)

        # Variant 4: Add "explain" prefix
        if not query_lower.startswith("explain"):
            variants.append(f"Explain {user_query.lower().rstrip('?')}")

        # Return unique variants up to max
        unique_variants = []
        seen = set()
        for v in variants:
            v_lower = v.lower().strip('?').strip()
            if v_lower not in seen:
                seen.add(v_lower)
                unique_variants.append(v)

        return unique_variants[:max_variants]

    @staticmethod
    def combine_variants(
        original_query: str,
        use_llm: bool = True,
        max_variants: int = 4
    ) -> List[str]:
        """
        Generate query variants, with fallback to simple expansion.

        Args:
            original_query: User's original query
            use_llm: Whether to try LLM-based expansion first
            max_variants: Maximum variants to generate

        Returns:
            List of query variants
        """

        if use_llm:
            try:
                variants = QueryExpansionService.expand_query(
                    original_query,
                    max_variants=max_variants
                )
                logger.info(f"Used LLM expansion: {len(variants)} variants")
                return variants
            except Exception as e:
                logger.warning(f"LLM expansion failed, falling back to simple: {e}")

        # Fallback to simple expansion
        variants = QueryExpansionService.expand_query_simple(
            original_query,
            max_variants=max_variants
        )
        logger.info(f"Used simple expansion: {len(variants)} variants")
        return variants
