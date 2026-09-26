import tempfile
import unittest
from pathlib import Path
from connections import *

def profile(name, base='https://example.com/v1', key='fake-key'):
    return {'name': name, 'mode': GATEWAY, 'base': base, 'key': key, 'model': 'model-a',
            'models': [{'id': 'model-a'}], 'catalog_base': base}

class PlatformTests(unittest.TestCase):
    def test_multiple_same_type_and_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = PlatformStore(tmp)
            a = s.save(None, profile('Platform A'))
            b = s.save(None, profile('Platform B', 'https://another.example/v1', 'another-fake-key'))
            s.activate(a)
            d = PlatformStore(tmp).data
            self.assertNotEqual(a,b)
            self.assertEqual(d['active'],a)
            self.assertEqual(d['platforms'][a]['base'],'https://example.com/v1')
            self.assertEqual(d['platforms'][b]['key'],'another-fake-key')
            self.assertEqual(d['platforms'][a]['models'],[{'id':'model-a'}])
            self.assertNotIn(b'fake-key', s.path.read_bytes())
    def test_edit_rename_and_delete_are_isolated(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=PlatformStore(tmp)
            a=s.save(None,profile('A')); b=s.save(None,profile('B'))
            s.save(a,profile('A renamed','https://updated.example/v1'))
            self.assertEqual(s.data['platforms'][b]['name'],'B')
            s.delete(a)
            d=PlatformStore(tmp).data
            self.assertNotIn(a,d['platforms']); self.assertIn(b,d['platforms'])
    def test_duplicate_name_rejected_without_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=PlatformStore(tmp); s.save(None,profile('A'))
            with self.assertRaises(ValueError): s.save(None,profile('a'))
            self.assertEqual(len(s.data['platforms']),1)
    def test_legacy_migration_does_not_resurrect_deleted_profiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            save_connections(tmp,{'active':GATEWAY,'profiles':{GATEWAY:profile('old'),CUSTOM:profile('second','https://second.example/v1')}})
            s=PlatformStore(tmp)
            self.assertEqual(len(s.data['platforms']),2)
            for ident in list(s.data['platforms']): s.delete(ident)
            self.assertEqual(PlatformStore(tmp).data['platforms'],{})

if __name__=='__main__': unittest.main(verbosity=2)
