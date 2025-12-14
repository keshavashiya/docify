"""
Prompt Engineering Service
Aggressive RAG prompting to prevent hallucinations and enforce citations
"""
import logging
from typing import List, Dict, Optional
from enum import Enum

from app.services.context_assembly import AssembledContext

logger = logging.getLogger(__name__)


class PromptType(str, Enum):
    """Types of prompts for different use cases"""
    QA = "qa"  # Question answering
    SUMMARY = "summary"  # Summarization
    COMPARE = "compare"  # Compare documents
    EXTRACT = "extract"  # Extract specific info
    EXPLAIN = "explain"  # Explain concepts


class PromptTemplate:
    """A prompt template with system and user components"""
    
    def __init__(
        self,
        system_prompt: str,
        user_template: str,
        prompt_type: PromptType = PromptType.QA
    ):
        self.system_prompt = system_prompt
        self.user_template = user_template
        self.prompt_type = prompt_type
    
    def format(self, **kwargs) -> Dict[str, str]:
        """Format the template with provided values"""
        return {
            "system": self.system_prompt,
            "user": self.user_template.format(**kwargs)
        }


class PromptEngineeringService:
    """Service for building grounded, citation-enforced prompts"""
    
    # System prompt - aggressive anti-hallucination
    SYSTEM_PROMPT_RAG = """You are Docify, an AI research assistant with access to a private knowledge base.
Your role is to answer questions based ONLY on the provided documents.

CRITICAL RULES - YOU MUST FOLLOW THESE:
1. ONLY use information from the provided context below
2. If information is NOT in the context, say "This information is not available in the provided documents"
3. ALWAYS cite your sources using [Source N] format where N matches the source number
4. NEVER make up or infer information not explicitly stated in the sources
5. NEVER cite sources that weren't provided to you
6. If sources disagree, mention BOTH perspectives with their citations

CITATION FORMAT:
- For direct quotes: "quoted text" [Source N]
- For paraphrased info: paraphrased statement [Source N]
- For synthesized info from multiple sources: statement [Source N, Source M]

RESPONSE STRUCTURE:
1. Answer the question directly first
2. Provide supporting details with citations
3. If relevant, note any limitations or gaps in the available information

REMEMBER: It is better to say "I don't have this information" than to guess or make something up."""

    SYSTEM_PROMPT_SUMMARY = """You are Docify, an AI research assistant tasked with summarizing documents.
Your role is to create accurate summaries based ONLY on the provided content.

CRITICAL RULES:
1. Summarize ONLY what is explicitly stated in the documents
2. Do NOT add interpretations or external knowledge
3. Cite specific sources for key points using [Source N] format
4. Maintain the original meaning - do not distort or exaggerate
5. If documents conflict, present both views with citations

STRUCTURE:
1. Key findings/main points (with citations)
2. Supporting details (with citations)
3. Any noted limitations or caveats from the sources"""

    SYSTEM_PROMPT_COMPARE = """You are Docify, an AI research assistant comparing information across documents.
Your role is to identify similarities, differences, and relationships based ONLY on the provided content.

CRITICAL RULES:
1. Compare ONLY information explicitly stated in the documents
2. Do NOT infer relationships not directly supported by text
3. Cite each comparison point: "Document A says X [Source N] while Document B says Y [Source M]"
4. Highlight agreements and disagreements clearly
5. Do NOT favor one source over another without explicit evidence

STRUCTURE:
1. Similarities (with citations from both sources)
2. Differences (with citations showing the contrast)
3. Synthesis or conclusion (only if directly supported)"""

    SYSTEM_PROMPT_EXTRACT = """You are Docify, an AI research assistant extracting specific information.
Your role is to find and present requested information based ONLY on the provided documents.

CRITICAL RULES:
1. Extract ONLY what is explicitly stated
2. If the requested information is not present, say so clearly
3. Cite the exact source for each piece of extracted information [Source N]
4. Use direct quotes when precision matters
5. Do NOT paraphrase in ways that change meaning

FORMAT:
- Present extracted information clearly
- Include source citations for each item
- Note if information is partial or incomplete"""

    # User prompt templates
    USER_TEMPLATE_QA = """Based on the following sources from your knowledge base:

{context}

---

USER QUESTION: {query}

---

Answer the question using ONLY the sources provided above. Cite your sources using [Source N] format.
If the answer is not in the sources, say "This information is not available in the provided documents."
"""

    USER_TEMPLATE_SUMMARY = """Summarize the following documents from your knowledge base:

{context}

---

USER REQUEST: {query}

---

Create a comprehensive summary using ONLY the content above. Cite key points using [Source N] format.
"""

    USER_TEMPLATE_COMPARE = """Compare the following documents from your knowledge base:

{context}

---

USER REQUEST: {query}

---

Compare and contrast the information across sources. Cite each point using [Source N] format.
"""

    USER_TEMPLATE_EXTRACT = """Extract information from the following documents:

{context}

---

USER REQUEST: {query}

---

Extract the requested information using ONLY the sources above. Cite each extracted item using [Source N] format.
If the information is not present, state that clearly.
"""

    # Templates registry
    TEMPLATES = {
        PromptType.QA: PromptTemplate(
            SYSTEM_PROMPT_RAG,
            USER_TEMPLATE_QA,
            PromptType.QA
        ),
        PromptType.SUMMARY: PromptTemplate(
            SYSTEM_PROMPT_SUMMARY,
            USER_TEMPLATE_SUMMARY,
            PromptType.SUMMARY
        ),
        PromptType.COMPARE: PromptTemplate(
            SYSTEM_PROMPT_COMPARE,
            USER_TEMPLATE_COMPARE,
            PromptType.COMPARE
        ),
        PromptType.EXTRACT: PromptTemplate(
            SYSTEM_PROMPT_EXTRACT,
            USER_TEMPLATE_EXTRACT,
            PromptType.EXTRACT
        ),
        PromptType.EXPLAIN: PromptTemplate(
            SYSTEM_PROMPT_RAG,  # Use QA for explain
            USER_TEMPLATE_QA,
            PromptType.EXPLAIN
        ),
    }

    def __init__(self):
        pass
    
    def build_prompt(
        self,
        query: str,
        context: AssembledContext,
        prompt_type: PromptType = PromptType.QA,
        conversation_history: Optional[List[Dict]] = None,
        additional_instructions: Optional[str] = None
    ) -> Dict[str, str]:
        """
        Build a complete prompt with context and anti-hallucination guardrails.
        
        Args:
            query: User's question
            context: Assembled context from ContextAssemblyService
            prompt_type: Type of prompt to generate
            conversation_history: Previous messages for context
            additional_instructions: Extra instructions to add
            
        Returns:
            Dict with 'system' and 'user' prompt strings
        """
        logger.info(f"Building {prompt_type.value} prompt for query: {query[:50]}...")
        
        # Get the appropriate template
        template = self.TEMPLATES.get(prompt_type, self.TEMPLATES[PromptType.QA])
        
        # Format the context for the prompt
        formatted_context = self._format_context_for_prompt(context)
        
        # Build the system prompt
        system_prompt = template.system_prompt
        
        # Add conflict warning if present
        if context.has_conflicts and context.conflict_summary:
            system_prompt += f"\n\nNOTE: Some sources may contain conflicting information. When you encounter conflicts, present both perspectives with citations."
        
        # Add additional instructions if provided
        if additional_instructions:
            system_prompt += f"\n\nADDITIONAL INSTRUCTIONS:\n{additional_instructions}"
        
        # Add conversation history context if present
        if conversation_history:
            history_context = self._format_conversation_history(conversation_history)
            system_prompt += f"\n\nPREVIOUS CONVERSATION:\n{history_context}"
        
        # Build the user prompt
        user_prompt = template.user_template.format(
            context=formatted_context,
            query=query
        )
        
        logger.info(f"Prompt built: system={len(system_prompt)} chars, user={len(user_prompt)} chars")
        
        return {
            "system": system_prompt,
            "user": user_prompt,
            "prompt_type": prompt_type.value,
            "source_count": context.source_count,
            "has_conflicts": context.has_conflicts
        }
    
    def _format_context_for_prompt(self, context: AssembledContext) -> str:
        """Format assembled context into a string for the prompt"""
        sections = []
        source_index = 1
        
        # Primary sources
        for chunk in context.primary_chunks:
            section = self._format_chunk_for_prompt(chunk, source_index)
            sections.append(section)
            source_index += 1
        
        # Supporting sources
        for chunk in context.supporting_chunks:
            section = self._format_chunk_for_prompt(chunk, source_index)
            sections.append(section)
            source_index += 1
        
        return "\n\n".join(sections)
    
    def _format_chunk_for_prompt(self, chunk: Dict, source_index: int) -> str:
        """Format a single chunk for inclusion in prompt"""
        lines = [f"[Source {source_index}]"]
        lines.append(f"Document: {chunk['title']}")
        lines.append(f"Type: {chunk['type']}")
        
        # Add metadata if available
        metadata = chunk.get('metadata', {})
        if metadata.get('section'):
            lines.append(f"Section: {metadata['section']}")
        if metadata.get('page'):
            lines.append(f"Page: {metadata['page']}")
        
        lines.append(f"Relevance: {chunk['score']:.2f}")
        lines.append("")
        lines.append(chunk['content'])
        lines.append(f"[End Source {source_index}]")
        
        return "\n".join(lines)
    
    def _format_conversation_history(
        self,
        history: List[Dict],
        max_turns: int = 5
    ) -> str:
        """Format conversation history for context"""
        # Take last N turns
        recent = history[-max_turns * 2:] if len(history) > max_turns * 2 else history
        
        formatted = []
        for msg in recent:
            role = msg.get('role', 'user').upper()
            content = msg.get('content', '')
            # Truncate long messages
            if len(content) > 500:
                content = content[:500] + "..."
            formatted.append(f"{role}: {content}")
        
        return "\n".join(formatted)
    
    def build_followup_prompt(
        self,
        query: str,
        context: AssembledContext,
        previous_answer: str,
        conversation_history: List[Dict]
    ) -> Dict[str, str]:
        """Build a prompt for follow-up questions"""
        
        # Add context about the previous answer
        additional = f"""This is a follow-up question. The previous answer was:
"{previous_answer[:500]}..."

If this follow-up relates to the previous answer, maintain consistency.
If it's a new topic, treat it as a fresh question using only the provided sources."""
        
        return self.build_prompt(
            query=query,
            context=context,
            prompt_type=PromptType.QA,
            conversation_history=conversation_history,
            additional_instructions=additional
        )
    
    def build_clarification_prompt(
        self,
        original_query: str,
        clarification: str,
        context: AssembledContext
    ) -> Dict[str, str]:
        """Build a prompt when user provides clarification"""
        
        combined_query = f"Original question: {original_query}\nClarification: {clarification}"
        
        additional = """The user has provided clarification for their question. 
Use both the original question and the clarification to provide a more targeted answer."""
        
        return self.build_prompt(
            query=combined_query,
            context=context,
            prompt_type=PromptType.QA,
            additional_instructions=additional
        )
    
    def get_no_context_response(self, query: str) -> str:
        """Get a response when no relevant context was found"""
        return f"""I couldn't find any relevant information in your documents to answer: "{query}"

This could mean:
1. The topic isn't covered in your uploaded documents
2. The question might need to be rephrased
3. You may need to upload documents containing this information

Would you like to:
- Rephrase your question?
- Upload relevant documents?
- Ask about a different topic?"""
    
    def get_low_confidence_prefix(self) -> str:
        """Get a prefix for low-confidence answers"""
        return """⚠️ **Note:** The following answer is based on limited relevant sources. 
The information may be incomplete. Please verify against the cited sources.

---

"""
    
    def estimate_prompt_tokens(self, prompt: Dict[str, str]) -> int:
        """Estimate token count for a prompt"""
        total_chars = len(prompt.get('system', '')) + len(prompt.get('user', ''))
        return total_chars // 4  # Conservative estimate
    
    @classmethod
    def get_available_prompt_types(cls) -> List[str]:
        """Get list of available prompt types"""
        return [pt.value for pt in PromptType]
