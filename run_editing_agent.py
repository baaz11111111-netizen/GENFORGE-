"""
Wrapper to route calls directly to the primary orchestrator engine.
"""
import sys
from orchestrator import run_editing_agent

# Allows direct CLI testing from terminal: python run_editing_agent.py
if __name__ == "__main__":
    test_prompt = "Speed up to 1.2x, apply cinematic color preset, and remove silent pauses."
    test_files = ["uploads/sample.mp4"]
    
    print("🚀 Testing Orchestrator Engine via CLI...")
    try:
        output_file = run_editing_agent(user_prompt=test_prompt, media_paths=test_files)
        print(f"✅ Render Complete: {output_file}")
    except Exception as e:
        print(f"❌ Test Failed: {e}")