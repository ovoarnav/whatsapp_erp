#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
from typing import List, Dict, Any

IMAGE_EXT={'.jpg','.jpeg','.png','.webp'}
VIDEO_EXT={'.mp4','.mov','.m4v'}
AUDIO_EXT={'.ogg','.opus','.m4a','.mp3','.wav'}
DOC_EXT={'.pdf'}


def media_type_for(path:str)->str:
    ext=Path(path).suffix.lower()
    if ext in IMAGE_EXT: return 'image'
    if ext in VIDEO_EXT: return 'video'
    if ext in AUDIO_EXT: return 'audio'
    if ext in DOC_EXT: return 'document'
    return 'unknown'


def extract_video_frames(video_path:str, out_dir:str, every_n_seconds:float=2.0, max_frames:int=5)->List[Dict[str,Any]]:
    frames=[]
    try:
        import cv2  # type: ignore
    except Exception:
        return frames
    cap=cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return frames
    fps=cap.get(cv2.CAP_PROP_FPS) or 0
    if fps<=0: fps=24.0
    step=max(1,int(fps*every_n_seconds))
    outp=Path(out_dir); outp.mkdir(parents=True,exist_ok=True)
    i=saved=0
    while saved<max_frames:
        ok,frame=cap.read()
        if not ok: break
        if i%step==0:
            fp=outp/f"frame_{saved:03d}.jpg"
            cv2.imwrite(str(fp),frame)
            frames.append({"frame_path":str(fp),"frame_timestamp":round(i/fps,2)})
            saved+=1
        i+=1
    cap.release()
    return frames
