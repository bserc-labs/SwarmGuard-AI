import os
import json
from typing import Dict, Any

class ExplanationEngine:
    """
    Generates operator-friendly explanations for cyber/RF attacks on the drone.
    Uses the knowledge base JSON files under backend/data/.
    """
    def __init__(self, data_dir: str = None):
        if data_dir is None:
            # Resolve 'backend/data/' relative to the utils folder
            current_dir = os.path.dirname(os.path.abspath(__file__))
            self.data_dir = os.path.normpath(os.path.join(current_dir, "..", "data"))
        else:
            self.data_dir = data_dir

    def load_attack_data(self, attack_type: str) -> Dict[str, Any]:
        """Loads the JSON data file for a specific attack type."""
        sanitized_name = os.path.basename(f"{attack_type}.json")
        file_path = os.path.join(self.data_dir, sanitized_name)
        
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Knowledge base file for attack '{attack_type}' not found.")
            
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def generate_explanation(self, attack_type: str) -> str:
        """
        Creates a clear, readable explanation describing:
        - What happened
        - Why it is dangerous
        - Key symptoms to watch for
        - Immediate operator directive
        """
        try:
            data = self.load_attack_data(attack_type)
            name = data.get("name", attack_type.replace("_", " ").title())
            description = data.get("Description", "No description available.")
            impact = data.get("Impact", "No impact details available.")
            symptoms = data.get("Symptoms", [])
            action = data.get("Recommended Action", "No recommended action available.")

            symptoms_bulleted = "\n".join([f"- {s}" for s in symptoms])

            explanation = (
                f"**Attack Type:** {name}\n\n"
                f"**What Happened:** {description}\n\n"
                f"**Why It Is Dangerous (Impact):** {impact}\n\n"
                f"**Key Symptoms Detected:**\n{symptoms_bulleted}\n\n"
                f"**Immediate Operator Directive:** {action}"
            )
            return explanation
        except Exception as e:
            return f"Error generating explanation for attack '{attack_type}': {str(e)}"
