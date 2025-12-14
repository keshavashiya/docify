"""
Citation Verification Service
Extracts citations from LLM responses and verifies them against source documents
"""
import logging
import re
from typing import List, Dict, Optional, Tuple, Set
from uuid import UUID
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from sqlalchemy.orm import Session

from app.models.models import Chunk, Resource
from app.services.context_assembly import AssembledContext

logger = logging.getLogger(__name__)


@dataclass
class ExtractedCitation:
    """A citation extracted from LLM response"""
    citation_id: int  # [Source N] - the N value
    claim_text: str  # The text making the claim
    source_reference: str  # The [Source N] text
    position: int  # Position in response text
    is_quote: bool = False  # Whether it's a direct quote


@dataclass
class VerifiedCitation:
    """A citation that has been verified against sources"""
    citation_id: int
    claim_text: str
    source_title: str
    source_type: str
    chunk_id: Optional[UUID] = None
    resource_id: Optional[UUID] = None
    page_number: Optional[int] = None
    section_title: Optional[str] = None
    verified: bool = False
    overlap_score: float = 0.0
    matching_text: Optional[str] = None
    verification_notes: str = ""


@dataclass
class VerificationResult:
    """Complete verification result for a response"""
    verified_citations: List[VerifiedCitation] = field(default_factory=list)
    unverified_claims: List[str] = field(default_factory=list)
    total_claims: int = 0
    verified_count: int = 0
    verification_score: float = 0.0
    has_hallucinations: bool = False
    hallucination_details: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return {
            "citations": [
                {
                    "citation_id": c.citation_id,
                    "claim": c.claim_text,
                    "source": c.source_title,
                    "source_type": c.source_type,
                    "chunk_id": str(c.chunk_id) if c.chunk_id else None,
                    "resource_id": str(c.resource_id) if c.resource_id else None,
                    "page": c.page_number,
                    "section": c.section_title,
                    "verified": c.verified,
                    "overlap_score": c.overlap_score,
                    "matching_text": c.matching_text[:200] if c.matching_text else None,
                    "notes": c.verification_notes
                }
                for c in self.verified_citations
            ],
            "unverified_claims": self.unverified_claims,
            "accuracy_metrics": {
                "total_claims": self.total_claims,
                "verified_claims": self.verified_count,
                "verification_score": self.verification_score,
                "has_hallucinations": self.has_hallucinations
            },
            "hallucination_details": self.hallucination_details,
            "warnings": self.warnings
        }


class CitationVerificationService:
    """Service for extracting and verifying citations in LLM responses"""
    
    # Regex patterns for citation extraction
    CITATION_PATTERN = re.compile(r'\[Source\s*(\d+)\]', re.IGNORECASE)
    QUOTE_PATTERN = re.compile(r'"([^"]+)"\s*\[Source\s*(\d+)\]', re.IGNORECASE)
    CLAIM_PATTERN = re.compile(r'([^.!?]+[.!?])\s*\[Source\s*(\d+)(?:,\s*Source\s*(\d+))?\]', re.IGNORECASE)
    
    # Thresholds
    MIN_OVERLAP_SCORE = 0.3  # Minimum overlap to consider verified
    HIGH_CONFIDENCE_THRESHOLD = 0.7  # High confidence verification
    
    def __init__(self, db: Session):
        self.db = db
    
    def verify_response(
        self,
        response_text: str,
        context: AssembledContext,
        strict_mode: bool = True
    ) -> VerificationResult:
        """
        Verify all citations in an LLM response against the provided context.
        
        Args:
            response_text: The LLM's response text
            context: The AssembledContext that was provided to the LLM
            strict_mode: If True, flag any claims without citations as potential hallucinations
            
        Returns:
            VerificationResult with detailed verification info
        """
        logger.info("Verifying citations in LLM response")
        
        result = VerificationResult()
        
        # Step 1: Build source map from context
        source_map = self._build_source_map(context)
        
        # Step 2: Extract all citations from response
        extracted = self._extract_citations(response_text)
        result.total_claims = len(extracted)
        
        logger.info(f"Extracted {len(extracted)} citations from response")
        
        # Step 3: Verify each citation
        for citation in extracted:
            verified = self._verify_citation(citation, source_map)
            result.verified_citations.append(verified)
            if verified.verified:
                result.verified_count += 1
        
        # Step 4: Check for uncited claims (potential hallucinations)
        if strict_mode:
            uncited = self._find_uncited_claims(response_text, extracted)
            result.unverified_claims = uncited
            if uncited:
                result.has_hallucinations = True
                result.hallucination_details = [
                    f"Uncited claim: {claim[:100]}..." for claim in uncited[:5]
                ]
        
        # Step 5: Check for invalid source references
        invalid_refs = self._find_invalid_references(extracted, source_map)
        if invalid_refs:
            result.has_hallucinations = True
            result.hallucination_details.extend([
                f"Invalid source reference: [Source {ref}]" for ref in invalid_refs
            ])
            result.warnings.append(
                f"Response references {len(invalid_refs)} sources that were not provided"
            )
        
        # Step 6: Calculate verification score
        if result.total_claims > 0:
            result.verification_score = result.verified_count / result.total_claims
        else:
            # No citations found - check if response makes claims
            if self._response_makes_claims(response_text):
                result.verification_score = 0.0
                result.has_hallucinations = True
                result.warnings.append("Response makes claims but has no citations")
            else:
                result.verification_score = 1.0  # No claims to verify
        
        # Step 7: Add warnings for low-confidence verifications
        low_conf_count = sum(
            1 for c in result.verified_citations 
            if c.verified and c.overlap_score < self.HIGH_CONFIDENCE_THRESHOLD
        )
        if low_conf_count > 0:
            result.warnings.append(
                f"{low_conf_count} citations have low overlap scores (may be paraphrased)"
            )
        
        logger.info(
            f"Verification complete: {result.verified_count}/{result.total_claims} verified, "
            f"score={result.verification_score:.2f}"
        )
        
        return result
    
    def _build_source_map(self, context: AssembledContext) -> Dict[int, Dict]:
        """Build a map of source numbers to their content and metadata"""
        source_map = {}
        source_index = 1
        
        # Primary chunks
        for chunk in context.primary_chunks:
            source_map[source_index] = {
                "chunk_id": chunk.get("chunk_id"),
                "resource_id": chunk.get("resource_id"),
                "title": chunk.get("title", "Unknown"),
                "type": chunk.get("type", "document"),
                "content": chunk.get("content", ""),
                "page": chunk.get("metadata", {}).get("page"),
                "section": chunk.get("metadata", {}).get("section")
            }
            source_index += 1
        
        # Supporting chunks
        for chunk in context.supporting_chunks:
            source_map[source_index] = {
                "chunk_id": chunk.get("chunk_id"),
                "resource_id": chunk.get("resource_id"),
                "title": chunk.get("title", "Unknown"),
                "type": chunk.get("type", "document"),
                "content": chunk.get("content", ""),
                "page": chunk.get("metadata", {}).get("page"),
                "section": chunk.get("metadata", {}).get("section")
            }
            source_index += 1
        
        return source_map
    
    def _extract_citations(self, response_text: str) -> List[ExtractedCitation]:
        """Extract all citations from response text"""
        citations = []
        seen_positions = set()
        
        # First, extract quoted citations (higher priority)
        for match in self.QUOTE_PATTERN.finditer(response_text):
            quote_text = match.group(1)
            source_num = int(match.group(2))
            position = match.start()
            
            if position not in seen_positions:
                citations.append(ExtractedCitation(
                    citation_id=source_num,
                    claim_text=quote_text,
                    source_reference=f"[Source {source_num}]",
                    position=position,
                    is_quote=True
                ))
                seen_positions.add(position)
        
        # Then extract claim-based citations
        for match in self.CLAIM_PATTERN.finditer(response_text):
            claim_text = match.group(1).strip()
            source_num = int(match.group(2))
            position = match.start()
            
            # Skip if we already have this position (from quote extraction)
            if position in seen_positions:
                continue
            
            citations.append(ExtractedCitation(
                citation_id=source_num,
                claim_text=claim_text,
                source_reference=f"[Source {source_num}]",
                position=position,
                is_quote=False
            ))
            seen_positions.add(position)
            
            # Check for additional source in same citation [Source 1, Source 2]
            if match.group(3):
                second_source = int(match.group(3))
                citations.append(ExtractedCitation(
                    citation_id=second_source,
                    claim_text=claim_text,
                    source_reference=f"[Source {second_source}]",
                    position=position,
                    is_quote=False
                ))
        
        # Sort by position
        citations.sort(key=lambda x: x.position)
        return citations
    
    def _verify_citation(
        self,
        citation: ExtractedCitation,
        source_map: Dict[int, Dict]
    ) -> VerifiedCitation:
        """Verify a single citation against source content"""
        
        source = source_map.get(citation.citation_id)
        
        if not source:
            # Source doesn't exist in context
            return VerifiedCitation(
                citation_id=citation.citation_id,
                claim_text=citation.claim_text,
                source_title="Unknown",
                source_type="unknown",
                verified=False,
                overlap_score=0.0,
                verification_notes="Referenced source was not provided in context"
            )
        
        # Calculate overlap between claim and source content
        overlap_score = self._calculate_overlap(
            citation.claim_text,
            source["content"],
            is_quote=citation.is_quote
        )
        
        # Find the best matching text in source
        matching_text = self._find_matching_text(
            citation.claim_text,
            source["content"]
        )
        
        verified = overlap_score >= self.MIN_OVERLAP_SCORE
        
        # Generate verification notes
        if verified:
            if overlap_score >= self.HIGH_CONFIDENCE_THRESHOLD:
                notes = "High confidence match"
            else:
                notes = "Partial match - may be paraphrased"
        else:
            notes = "Could not verify claim against source content"
        
        return VerifiedCitation(
            citation_id=citation.citation_id,
            claim_text=citation.claim_text,
            source_title=source["title"],
            source_type=source["type"],
            chunk_id=UUID(source["chunk_id"]) if source.get("chunk_id") else None,
            resource_id=UUID(source["resource_id"]) if source.get("resource_id") else None,
            page_number=source.get("page"),
            section_title=source.get("section"),
            verified=verified,
            overlap_score=overlap_score,
            matching_text=matching_text,
            verification_notes=notes
        )
    
    def _calculate_overlap(
        self,
        claim: str,
        source_content: str,
        is_quote: bool = False
    ) -> float:
        """Calculate semantic overlap between claim and source"""
        
        # Normalize texts
        claim_normalized = claim.lower().strip()
        source_normalized = source_content.lower()
        
        if is_quote:
            # For quotes, check if the quote exists in source
            if claim_normalized in source_normalized:
                return 1.0
            # Check for near-match (minor differences)
            matcher = SequenceMatcher(None, claim_normalized, source_normalized)
            # Find the best matching block
            match = matcher.find_longest_match(0, len(claim_normalized), 0, len(source_normalized))
            if match.size > len(claim_normalized) * 0.8:
                return 0.9
        
        # For paraphrased claims, use word overlap
        claim_words = set(self._tokenize(claim_normalized))
        source_words = set(self._tokenize(source_normalized))
        
        if not claim_words:
            return 0.0
        
        # Calculate Jaccard-like overlap
        overlap = claim_words & source_words
        
        # Weight by claim coverage (what % of claim words are in source)
        claim_coverage = len(overlap) / len(claim_words)
        
        # Also check for key phrase matches
        key_phrases = self._extract_key_phrases(claim_normalized)
        phrase_matches = sum(1 for phrase in key_phrases if phrase in source_normalized)
        phrase_score = phrase_matches / len(key_phrases) if key_phrases else 0
        
        # Combine scores
        return (claim_coverage * 0.6) + (phrase_score * 0.4)
    
    def _find_matching_text(self, claim: str, source_content: str) -> Optional[str]:
        """Find the best matching text segment in source for the claim"""
        claim_normalized = claim.lower().strip()
        source_normalized = source_content.lower()
        
        # If exact match, return it
        if claim_normalized in source_normalized:
            start = source_normalized.find(claim_normalized)
            return source_content[start:start + len(claim)]
        
        # Otherwise, find the best matching window
        claim_words = self._tokenize(claim_normalized)
        if not claim_words:
            return None
        
        # Slide a window and find best match
        source_words = source_content.split()
        window_size = min(len(claim_words) * 2, len(source_words))
        
        best_match = ""
        best_score = 0
        
        for i in range(len(source_words) - window_size + 1):
            window = " ".join(source_words[i:i + window_size])
            window_set = set(self._tokenize(window.lower()))
            claim_set = set(claim_words)
            
            overlap = len(window_set & claim_set) / len(claim_set) if claim_set else 0
            if overlap > best_score:
                best_score = overlap
                best_match = window
        
        return best_match if best_score > 0.3 else None
    
    def _tokenize(self, text: str) -> List[str]:
        """Simple tokenization - remove punctuation and split"""
        # Remove punctuation and split
        cleaned = re.sub(r'[^\w\s]', ' ', text)
        words = cleaned.split()
        # Filter out very short words and stopwords
        stopwords = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 
                     'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
                     'would', 'could', 'should', 'may', 'might', 'must', 'shall',
                     'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by', 'from',
                     'as', 'into', 'through', 'during', 'before', 'after', 'above',
                     'below', 'between', 'under', 'again', 'further', 'then', 'once',
                     'and', 'but', 'or', 'nor', 'so', 'yet', 'both', 'either',
                     'neither', 'not', 'only', 'own', 'same', 'than', 'too', 'very',
                     'just', 'also', 'now', 'here', 'there', 'when', 'where', 'why',
                     'how', 'all', 'each', 'every', 'both', 'few', 'more', 'most',
                     'other', 'some', 'such', 'no', 'any', 'this', 'that', 'these',
                     'those', 'it', 'its'}
        return [w for w in words if len(w) > 2 and w not in stopwords]
    
    def _extract_key_phrases(self, text: str) -> List[str]:
        """Extract key phrases (2-3 word combinations) from text"""
        words = self._tokenize(text)
        phrases = []
        
        # Bigrams
        for i in range(len(words) - 1):
            phrases.append(f"{words[i]} {words[i+1]}")
        
        # Trigrams
        for i in range(len(words) - 2):
            phrases.append(f"{words[i]} {words[i+1]} {words[i+2]}")
        
        return phrases
    
    def _find_uncited_claims(
        self,
        response_text: str,
        extracted_citations: List[ExtractedCitation]
    ) -> List[str]:
        """Find statements that look like claims but have no citations"""
        uncited = []
        
        # Get positions of all citations
        cited_positions = {c.position for c in extracted_citations}
        
        # Find sentences that make claims (contain factual-sounding language)
        claim_indicators = [
            r'according to',
            r'research shows',
            r'studies indicate',
            r'data suggests',
            r'it is known that',
            r'evidence shows',
            r'results demonstrate',
            r'findings reveal',
            r'\d+%',  # Percentages
            r'\d+ percent',
            r'the study found',
            r'experiments show',
        ]
        
        sentences = re.split(r'(?<=[.!?])\s+', response_text)
        
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            
            # Check if this sentence has a citation
            has_citation = bool(self.CITATION_PATTERN.search(sentence))
            
            if not has_citation:
                # Check if it looks like a factual claim
                for indicator in claim_indicators:
                    if re.search(indicator, sentence, re.IGNORECASE):
                        uncited.append(sentence)
                        break
        
        return uncited
    
    def _find_invalid_references(
        self,
        extracted_citations: List[ExtractedCitation],
        source_map: Dict[int, Dict]
    ) -> List[int]:
        """Find citation references that don't exist in the source map"""
        invalid = []
        seen = set()
        
        for citation in extracted_citations:
            if citation.citation_id not in source_map and citation.citation_id not in seen:
                invalid.append(citation.citation_id)
                seen.add(citation.citation_id)
        
        return invalid
    
    def _response_makes_claims(self, response_text: str) -> bool:
        """Check if the response makes factual claims (vs just saying it doesn't know)"""
        
        # Patterns indicating the model declined to answer
        no_info_patterns = [
            r"i don't have",
            r"i cannot find",
            r"not available in",
            r"no information",
            r"not in the documents",
            r"not covered in",
            r"i couldn't find",
            r"no relevant",
        ]
        
        response_lower = response_text.lower()
        
        # If the response is primarily a "no information" response, it's not making claims
        for pattern in no_info_patterns:
            if re.search(pattern, response_lower):
                # Check if this is the main point of the response (not a side note)
                if len(response_text) < 500:
                    return False
        
        # Otherwise, if the response has substantial content, it's likely making claims
        return len(response_text) > 100
    
    def get_verification_summary(self, result: VerificationResult) -> str:
        """Get a human-readable summary of verification results"""
        
        if result.verification_score >= 0.9:
            status = "✅ Highly Verified"
        elif result.verification_score >= 0.7:
            status = "✓ Mostly Verified"
        elif result.verification_score >= 0.5:
            status = "⚠️ Partially Verified"
        else:
            status = "❌ Low Verification"
        
        summary = [
            f"**Verification Status:** {status}",
            f"**Score:** {result.verification_score:.0%}",
            f"**Citations:** {result.verified_count}/{result.total_claims} verified",
        ]
        
        if result.has_hallucinations:
            summary.append("**⚠️ Potential Issues Detected**")
            for detail in result.hallucination_details[:3]:
                summary.append(f"  - {detail}")
        
        if result.warnings:
            summary.append("**Notes:**")
            for warning in result.warnings:
                summary.append(f"  - {warning}")
        
        return "\n".join(summary)
