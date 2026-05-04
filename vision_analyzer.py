#!/usr/bin/env python3
from __future__ import annotations
from typing import Dict, Any, List
from pathlib import Path

DEFAULT_VISION_MODEL="HuggingFaceTB/SmolVLM2-500M-Video-Instruct"

class VisionAnalyzer:
    def analyze_image(self, image_path:str, context_text:str|None=None)->Dict[str,Any]: raise NotImplementedError
    def analyze_video(self, video_path:str, frame_paths:List[str], context_text:str|None=None)->Dict[str,Any]: raise NotImplementedError

class MockVisionAnalyzer(VisionAnalyzer):
    def _from_name(self,name:str,media_type:str):
        n=name.lower(); obs=[]
        trade=['unknown']; risks=['scope_uncertainty']
        if any(k in n for k in ['tile','shower','bath']): trade=['tile']; risks=['water_damage','unknown_site_condition']
        if any(k in n for k in ['roof','ceiling']): trade=['roofing']; risks=['water_damage','unknown_site_condition']
        if any(k in n for k in ['outlet','panel','wire']): trade=['electrical']; risks=['safety_or_code_risk']
        if any(k in n for k in ['leak','pipe','toilet']): trade=['plumbing']; risks=['water_damage']
        obs.append({"observation":"Image appears to show possible issue; cannot confirm from media alone.","confidence":0.55,"evidence_type":media_type,"media_id":None,"frame_timestamp":None,"possible_trade_categories":trade,"possible_risks":risks})
        return obs
    def analyze_image(self,image_path,context_text=None):
        obs=self._from_name(Path(image_path).name,'image')
        return {"visual_observations":obs,"media_summary":"Possible visible issue from image; inspection recommended.","recommended_followup_questions":["Can you share one wider photo and one close-up?","Is the issue active right now (e.g., leak/sparking)?"],"model_used":"mock-vision","analysis_mode":"mock"}
    def analyze_video(self,video_path,frame_paths,context_text=None):
        obs=self._from_name(Path(video_path).name,'video')
        for i,_ in enumerate(frame_paths[:2]): obs.append({**obs[0],"evidence_type":"video_frame","frame_timestamp":str(i*2)})
        return {"visual_observations":obs,"media_summary":"Video suggests possible issue, but exact root cause is not confirmable from footage alone.","recommended_followup_questions":["Can you confirm exact location and when this started?"],"model_used":"mock-vision","analysis_mode":"mock"}

class SmolVLMVisionAnalyzer(VisionAnalyzer):
    def __init__(self, model_name:str=DEFAULT_VISION_MODEL):
        self.model_name=model_name
    def _failed(self,msg:str):
        return {"visual_observations":[],"media_summary":msg,"recommended_followup_questions":[],"model_used":self.model_name,"analysis_mode":"failed"}
    def analyze_image(self,image_path,context_text=None):
        try:
            from transformers import pipeline
            pipe=pipeline("image-to-text",model=self.model_name)
            out=pipe(image_path,max_new_tokens=60)
            txt=str(out[0].get('generated_text','')) if out else ''
            return {"visual_observations":[{"observation":f"Possible visual finding: {txt[:180]}","confidence":0.45,"evidence_type":"image","media_id":None,"frame_timestamp":None,"possible_trade_categories":["unknown"],"possible_risks":["scope_uncertainty"]}],"media_summary":"SmolVLM observation generated; cannot confirm from image alone.","recommended_followup_questions":["Can you share additional angles or measurements?"],"model_used":self.model_name,"analysis_mode":"smolvlm"}
        except Exception as e:
            return self._failed(f"SmolVLM image analysis failed: {e}")
    def analyze_video(self,video_path,frame_paths,context_text=None):
        # lightweight fallback: analyze first frame if present
        if frame_paths:
            return self.analyze_image(frame_paths[0],context_text)
        return self._failed("No extracted frames available for video analysis.")


def get_vision_analyzer(mode:str='auto', model_name:str=DEFAULT_VISION_MODEL):
    if mode=='mock': return MockVisionAnalyzer()
    if mode=='smolvlm':
        return SmolVLMVisionAnalyzer(model_name)
    # auto
    analyzer=SmolVLMVisionAnalyzer(model_name)
    probe=analyzer.analyze_image(__file__)  # expected fail quickly due non-image
    if probe.get('analysis_mode')=='failed':
        return MockVisionAnalyzer()
    return analyzer
