import numpy as np
from sentence_transformers import SentenceTransformer, util
import re

class NaturalEmailAssistant:
    def __init__(self):
        self.model = SentenceTransformer('all-MiniLM-L6-v2', device='cpu')
        
    def detect_data_type(self, data: list) -> dict:
        """Intelligently detect what type of data user uploaded"""
        if not data:
            return {"type": "unknown", "confidence": 0.0}
        
        sample = data[0]
        field_names = list(sample.keys())
        field_names_lower = [f.lower() for f in field_names]
        
        # School/Education Data Detection
        school_keywords = ['student', 'school', 'class', 'grade', 'marks', 'subject', 'exam', 'roll', 'admission']
        school_score = sum(1 for keyword in school_keywords if any(keyword in field.lower() for field in field_names_lower))
        
        # Company/Employee Data Detection
        company_keywords = ['employee', 'department', 'designation', 'salary', 'manager', 'team', 'branch', 'office']
        company_score = sum(1 for keyword in company_keywords if any(keyword in field.lower() for field in field_names_lower))
        
        # Contact/CRM Data Detection
        contact_keywords = ['name', 'email', 'phone', 'address', 'city', 'country', 'company', 'title']
        contact_score = sum(1 for keyword in contact_keywords if any(keyword in field.lower() for field in field_names_lower))
        
        # Sales/Customer Data Detection
        sales_keywords = ['customer', 'order', 'product', 'amount', 'date', 'status', 'payment', 'invoice']
        sales_score = sum(1 for keyword in sales_keywords if any(keyword in field.lower() for field in field_names_lower))
        
        scores = {
            "school_data": school_score,
            "company_data": company_score,
            "contact_data": contact_score,
            "sales_data": sales_score
        }
        
        best_type = max(scores, key=scores.get)
        confidence = scores[best_type] / max(len(field_names), 1)
        
        return {
            "type": best_type,
            "confidence": min(confidence, 1.0),
            "field_analysis": field_names,
            "scores": scores
        }
    
    def get_search_priority_fields(self, data_type: str, field_names: list) -> tuple:
        """Get priority fields based on detected data type"""
        field_names_lower = [f.lower() for f in field_names]
        
        if data_type == "school_data":
            # Priority: student info, academic details, location
            primary_fields = ['student', 'name', 'roll', 'admission']
            secondary_fields = ['school', 'class', 'grade', 'subject', 'marks', 'exam']
            location_fields = ['city', 'area', 'location', 'address', 'district']
            
        elif data_type == "company_data":
            # Priority: employee info, company details, location
            primary_fields = ['employee', 'name', 'id', 'code']
            secondary_fields = ['company', 'department', 'designation', 'team']
            location_fields = ['office', 'branch', 'city', 'location', 'area']
            
        elif data_type == "contact_data":
            # Priority: personal info, company, location
            primary_fields = ['name', 'first', 'last', 'full']
            secondary_fields = ['company', 'title', 'position', 'role']
            location_fields = ['city', 'state', 'country', 'address', 'area']
            
        elif data_type == "sales_data":
            # Priority: customer info, transaction details
            primary_fields = ['customer', 'name', 'id', 'code']
            secondary_fields = ['order', 'product', 'amount', 'date']
            location_fields = ['city', 'area', 'location', 'address']
            
        else:
            # Default: generic search
            primary_fields = ['name', 'id', 'code']
            secondary_fields = ['company', 'title', 'description']
            location_fields = ['city', 'location', 'area', 'address']
        
        # Map to actual field names in the data
        def map_fields(target_fields):
            mapped = []
            for target in target_fields:
                for field in field_names:
                    if target in field.lower():
                        mapped.append(field)
                        break
            return mapped
        
        return (
            map_fields(primary_fields),
            map_fields(secondary_fields),
            map_fields(location_fields)
        )
    
    def enhanced_search(self, data: list, query: str, top_k: int = 5) -> list:
        """Intelligent search that adapts to different data types"""
        if not data:
            return []
        
        # 1. Detect data type
        data_info = self.detect_data_type(data)
        data_type = data_info["type"]
        
        # 2. Get priority fields for this data type
        primary_fields, secondary_fields, location_fields = self.get_search_priority_fields(
            data_type, data_info["field_analysis"]
        )
        
        # 3. Prepare intelligent text representations
        texts = []
        for item in data:
            # Build primary text (most important fields)
            primary_text = " ".join(str(item.get(field, "")) for field in primary_fields if item.get(field))
            
            # Build secondary text (supporting fields)
            secondary_text = " ".join(str(item.get(field, "")) for field in secondary_fields if item.get(field))
            
            # Build location text (geographic fields)
            location_text = " ".join(str(item.get(field, "")) for field in location_fields if item.get(field))
            
            # Combine with priority weighting
            combined_text = f"{primary_text} | {secondary_text} | {location_text}"
            texts.append(combined_text)
        
        # 4. Enhanced query processing
        enhanced_query = self.enhance_query(query, data_type, primary_fields)
        
        # 5. Semantic search with the enhanced query
        query_emb = self.model.encode(enhanced_query, convert_to_tensor=True)
        doc_embs = self.model.encode(texts, convert_to_tensor=True)
        
        # 6. Hybrid scoring with field-specific boosts
        semantic_scores = util.pytorch_cos_sim(query_emb, doc_embs)[0].cpu().numpy()
        
        results = []
        for idx, score in enumerate(semantic_scores):
            # Apply field-specific scoring
            item = data[idx]
            field_boost = self.calculate_field_boost(item, query, primary_fields, secondary_fields, location_fields)
            
            # Combined score
            final_score = (score * 0.7) + (field_boost * 0.3)
            
            if final_score > 0.2:  # Lower threshold for better recall
                results.append({
                    **item,
                    "_score": float(final_score),
                    "_semantic_score": float(score),
                    "_field_boost": float(field_boost),
                    "_data_type": data_type,
                    "_matched_fields": self.find_matched_fields(item, query, primary_fields + secondary_fields + location_fields)
                })
        
        # Sort by final score
        results = sorted(results, key=lambda x: x["_score"], reverse=True)
        
        # Add data type info to results
        if results:
            results[0]["_data_analysis"] = data_info
        
        return results[:top_k]
    
    def enhance_query(self, query: str, data_type: str, primary_fields: list) -> str:
        """Enhance the search query based on data type and available fields"""
        enhanced = query.lower()
        
        # Add data type context
        if data_type == "school_data":
            enhanced += " student school education academic"
        elif data_type == "company_data":
            enhanced += " employee company business professional"
        elif data_type == "contact_data":
            enhanced += " contact person individual"
        elif data_type == "sales_data":
            enhanced += " customer sales transaction business"
        
        # Add field context if available
        if primary_fields:
            enhanced += " " + " ".join(primary_fields)
        
        return enhanced
    
    def calculate_field_boost(self, item: dict, query: str, primary_fields: list, secondary_fields: list, location_fields: list) -> float:
        """Calculate boost score based on field matches"""
        query_terms = query.lower().split()
        boost = 0.0
        
        # Primary fields get highest boost
        for field in primary_fields:
            if item.get(field):
                field_value = str(item[field]).lower()
                for term in query_terms:
                    if term in field_value:
                        boost += 0.4  # High boost for primary field matches
        
        # Secondary fields get medium boost
        for field in secondary_fields:
            if item.get(field):
                field_value = str(item[field]).lower()
                for term in query_terms:
                    if term in field_value:
                        boost += 0.2  # Medium boost for secondary field matches
        
        # Location fields get location-specific boost
        for field in location_fields:
            if item.get(field):
                field_value = str(item[field]).lower()
                for term in query_terms:
                    if term in field_value:
                        boost += 0.3  # Good boost for location matches
        
        return min(boost, 1.0)
    
    def find_matched_fields(self, item: dict, query: str, search_fields: list) -> list:
        """Find which fields contain the search query"""
        query_terms = query.lower().split()
        matched = []
        
        for field in search_fields:
            if item.get(field):
                field_value = str(item[field]).lower()
                for term in query_terms:
                    if term in field_value and field not in matched:
                        matched.append(field)
                        break
        
        return matched