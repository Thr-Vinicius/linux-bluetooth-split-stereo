import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest
import wave

spec=importlib.util.spec_from_file_location('references',Path(__file__).resolve().parents[1]/'tools/make-references.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)


class ReferenceTests(unittest.TestCase):
    def test_channels_and_center_are_known_and_faded(self):
        for side in ('L','R','C'):
            samples=list(struct.iter_unpack('<hh',r.pcm([(0,.1,side)],.2,48000)))
            self.assertEqual(samples[0],(0,0));self.assertEqual(samples[-1],(0,0))
            self.assertLessEqual(max(abs(v) for pair in samples for v in pair),round(32767*r.PEAK))
            if side=='L':self.assertTrue(all(b==0 for a,b in samples));self.assertTrue(any(a for a,b in samples))
            if side=='R':self.assertTrue(all(a==0 for a,b in samples));self.assertTrue(any(b for a,b in samples))
            if side=='C':self.assertTrue(all(a==b for a,b in samples))
            self.assertLess(max(abs(v) for pair in samples[:24] for v in pair),50)

    def test_files_are_stereo_48k_and_existing_directory_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'references';metadata=r.generate(path)
            for item in metadata['files'].values():
                with wave.open(str(path/item['file'])) as file:
                    self.assertEqual((file.getnchannels(),file.getsampwidth(),file.getframerate()),(2,2,48000))
                    self.assertEqual(file.getnframes(),item['seconds']*48000)
            with self.assertRaises(FileExistsError):r.generate(path)


if __name__=='__main__':unittest.main()
