#!/usr/bin/env python3
"""Create low-level, faded PCM references; never play or connect to audio."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
import wave

RATE=48000
PEAK=.025
SECTIONS={'left':[(1,3,'L')],'right':[(1,3,'R')],
          'center':[(1,3,'C')],'sequence':[(1,3,'L'),(5,7,'R'),(9,11,'C')]}


def pcm(sections, seconds, rate=RATE):
    data=bytearray()
    for frame in range(int(seconds*rate)):
        now=frame/rate
        left=right=0
        for start,end,side in sections:
            if start<=now<end:
                envelope=min(1,(now-start)/.03,(end-now)/.03)
                value=round(32767*PEAK*envelope*math.sin(2*math.pi*440*(now-start)))
                left=value if side in ('L','C') else 0
                right=value if side in ('R','C') else 0
                break
        data.extend(struct.pack('<hh',left,right))
    return bytes(data)


def generate(directory):
    directory=Path(directory)
    directory.mkdir(mode=0o700,parents=True,exist_ok=False)
    entries={}
    for name,sections in SECTIONS.items():
        duration=12 if name=='sequence' else 4
        path=directory/(name+'.wav')
        with wave.open(str(path),'wb') as output:
            output.setnchannels(2);output.setsampwidth(2);output.setframerate(RATE)
            output.writeframes(pcm(sections,duration))
        entries[name]=dict(file=path.name,seconds=duration,sections=sections,
                           sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    metadata=dict(sample_rate=RATE,bits=16,channels=2,peak_linear=PEAK,
                  peak_dbfs=20*math.log10(PEAK),tone_hz=440,fade_seconds=.03,
                  note='Electrical references only. No playback or acoustic calibration performed.',files=entries)
    (directory/'manifest.json').write_text(json.dumps(metadata,indent=2)+'\n')
    return metadata


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(generate(args.output),indent=2))


if __name__=='__main__':main()
