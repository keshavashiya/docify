"""
Query Planner Service
LLM-driven strategic query planning before retrieval (v2)

Analyzes user queries to determine:
- Query type (QA, comparison, summary, synthesis)
- Search strategy (semantic, keyword, hybrid)
- Number of documents needed
- Complexity estimation
"""
import logging
import json
import re
from typing import Optional, Dict, List
from dataclasses import dataclass, field
from enum import Enum

from app.services.llm import LLMService, get_llm_service

logger = logging.getLogger(__name__)


class QueryType(str, Enum):
    """Types of user queries"""
    QA = "qa"                    # Simple factual question
    COMPARISON = "comparison"    # Compare multiple items/concepts
    SUMMARY = "summary"          # Summarize document(s)
    SYNTHESIS = "synthesis"      # Combine info across documents
    ANALYSIS = "analysis"        # Deep analysis of a topic
    UNKNOWN = "unknown"


class SearchStrategy(str, Enum):
    """Search strategies"""
    SEMANTIC = "semantic"    # Vector similarity search
    KEYWORD = "keyword"      # BM25/keyword matching
    HYBRID = "hybrid"        # Combine both


@dataclass
class QueryPlan:
    """Strategic plan for executing a query"""
    query_type: QueryType
    search_strategy: SearchStrategy
    num_documents_needed: int
    requires_synthesis: bool
    estimated_complexity: int  # 1-10 scale
    confidence: float  # 0-1 confidence in plan
    reasoning: str = ""

    def to_dict(self) -> dict:
        return {
            "query_type": self.query_type.value,
            "search_strategy": self.search_strategy.value,
            "num_documents_needed": self.num_documents_needed,
            "requires_synthesis": self.requires_synthesis,
            "estimated_complexity": self.estimated_complexity,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
        }


class QueryPlanner:
    """
    LLM-driven query planning for intelligent retrieval.

    Analyzes queries before expensive retrieval operations to:
    1. Determine optimal search strategy
    2. Estimate number of documents needed
    3. Identify query complexity
    4. Decide on synthesis requirements
    """

    # Keywords for rule-based fallback
    COMPARISON_KEYWORDS = {"compare", "versus", "vs", "difference", "between", "better", "worse", "pros", "cons"}
    SUMMARY_KEYWORDS = {"summarize", "summary", "overview", "brief", "main points", "key points", "tldr"}
    SYNTHESIS_KEYWORDS = {"across", "multiple", "all", "combine", "together", "overall", "comprehensive"}

    def __init__(self, llm_service: Optional[LLMService] = None):
        self.llm = llm_service or get_llm_service()
        self._cache: Dict[str, QueryPlan] = {}  # Simple in-memory cache

    async def plan_query(
        self,
        query: str,
        use_llm: bool = True
    ) -> QueryPlan:
        """
        Determine search strategy and query type.
        """
        # 1. Check cache first
        cache_key = query.lower().strip()
        if cache_key in self._cache:
            return self._cache[cache_key]

        # 2. Optimized for speed: skip LLM for short/simple queries
        is_simple = len(query.split()) < 5 and not any(w in query.lower() for w in ["compare", "summarize", "analyze"])

        if not use_llm or is_simple:
            plan = self._plan_with_rules(query)
            if is_simple:
                plan.reasoning = "Simple short query - using rule-based planning (speed optimized)."
            self._cache[cache_key] = plan
            return plan

        # 3. Use LLM for strategic planning
        try:
            plan = await self._plan_with_llm(query)
            self._cache[cache_key] = plan
            return plan
        except Exception as e:
            logger.warning(f"LLM query planning failed: {e}. Falling back to rules.")
            plan = self._plan_with_rules(query)
            self._cache[cache_key] = plan
            return plan

    async def _plan_with_llm(self, query: str) -> QueryPlan:
        """Use LLM to analyze query and create plan"""
        prompt = f"""Analyze this user query and create a retrieval plan.

Query: "{query}"

Respond with ONLY a JSON object (no markdown, no explanation):
{{
    "query_type": "qa|comparison|summary|synthesis|analysis",
    "search_strategy": "semantic|keyword|hybrid",
    "num_documents_needed": 1-5,
    "requires_synthesis": true|false,
    "estimated_complexity": 1-10,
    "reasoning": "brief explanation"
}}

Guidelines:
- qa: Simple factual questions (1-2 docs)
- comparison: Comparing items (2-3 docs)
- summary: Summarizing content (1-2 docs)
- synthesis: Combining info across sources (3-5 docs)
- analysis: Deep dive into topic (2-4 docs)

Search strategy:
- semantic: Abstract/conceptual queries
- keyword: Specific terms, names, codes
- hybrid: General queries (most common)"""

        try:
            response = await self.llm.call(
                prompt,
                max_tokens=200,
                temperature=0.1  # Low temp for structured output
            )

            # Parse JSON response
            plan_dict = self._parse_json_response(response)

            return QueryPlan(
                query_type=QueryType(plan_dict.get("query_type", "qa")),
                search_strategy=SearchStrategy(plan_dict.get("search_strategy", "hybrid")),
                num_documents_needed=min(5, max(1, int(plan_dict.get("num_documents_needed", 3)))),
                requires_synthesis=bool(plan_dict.get("requires_synthesis", False)),
                estimated_complexity=min(10, max(1, int(plan_dict.get("estimated_complexity", 5)))),
                confidence=0.85,  # LLM-based plans have good confidence
                reasoning=plan_dict.get("reasoning", "")
            )

        except Exception as e:
            logger.error(f"Error in LLM query planning: {e}")
            raise

    def _plan_with_rules(self, query: str) -> QueryPlan:
        """Rule-based fallback for query planning"""
        query_lower = query.lower()
        words = set(query_lower.split())

        # Detect query type
        query_type = QueryType.QA
        requires_synthesis = False
        num_docs = 3

        if words & self.COMPARISON_KEYWORDS:
            query_type = QueryType.COMPARISON
            num_docs = 3
            requires_synthesis = True
        elif words & self.SUMMARY_KEYWORDS:
            query_type = QueryType.SUMMARY
            num_docs = 2
        elif words & self.SYNTHESIS_KEYWORDS:
            query_type = QueryType.SYNTHESIS
            num_docs = 5
            requires_synthesis = True
        elif "?" in query and len(query.split()) < 10:
            query_type = QueryType.QA
            num_docs = 2

        # Detect search strategy
        # Keywords with specific terms suggest keyword search
        has_specific_terms = bool(re.search(r'\b[A-Z][a-z]+[A-Z]', query))  # CamelCase
        has_quotes = '"' in query or "'" in query

        if has_specific_terms or has_quotes:
            search_strategy = SearchStrategy.KEYWORD
        elif len(query.split()) > 15:
            search_strategy = SearchStrategy.SEMANTIC
        else:
            search_strategy = SearchStrategy.HYBRID

        # Estimate complexity based on query length and type
        word_count = len(query.split())
        complexity = min(10, max(1, word_count // 3 + (3 if requires_synthesis else 0)))

        return QueryPlan(
            query_type=query_type,
            search_strategy=search_strategy,
            num_documents_needed=num_docs,
            requires_synthesis=requires_synthesis,
            estimated_complexity=complexity,
            confidence=0.6,  # Rule-based has lower confidence
            reasoning="Rule-based planning"
        )

    def _parse_json_response(self, response: str) -> dict:
        """Parse JSON from LLM response, handling various formats"""
        # Try direct parse
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            pass

        # Try extracting from markdown code block
        if "```json" in response:
            json_str = response.split("```json")[1].split("```")[0].strip()
            return json.loads(json_str)
        elif "```" in response:
            json_str = response.split("```")[1].split("```")[0].strip()
            return json.loads(json_str)

        # Try finding JSON object in response
        match = re.search(r'\{[^{}]*\}', response, re.DOTALL)
        if match:
            return json.loads(match.group())

        raise ValueError(f"Could not parse JSON from response: {response[:200]}")

    def clear_cache(self):
        """Clear the query plan cache"""
        self._cache.clear()
        logger.info("Query plan cache cleared")


# Singleton instance
_query_planner: Optional[QueryPlanner] = None


def get_query_planner() -> QueryPlanner:
    """Get or create query planner singleton"""
    global _query_planner
    if _query_planner is None:
        _query_planner = QueryPlanner()
    return _query_planner
