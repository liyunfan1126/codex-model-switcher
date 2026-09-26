"""GUI integration with fake API responses and isolated local configuration."""
import tempfile
import time
from pathlib import Path
from unittest.mock import patch
import unittest
import core
import app

class CardUITests(unittest.TestCase):
    def test_clean_start_cards_validate_switch_and_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            config=root/'codex'/'config.toml'
            core.atomic_write(config,b'model="original"\n')
            with patch.object(app,'data_path',return_value=root/'data'), patch.object(core,'data_path',return_value=root/'data'), patch.object(app,'config_path',return_value=config), patch.object(app.messagebox,'showinfo'):
                a=app.App()
                try:
                    a.update()
                    self.assertEqual(a.store.data['platforms'],{})
                    self.assertEqual(a.key.get(),'')
                    self.assertTrue(a.platforms_page.winfo_ismapped())
                    self.assertFalse(a.editor_page.winfo_ismapped())
                    self.assertEqual(len(a.card_models),0)
                    def profile(name,key,model):
                        return {'name':name,'mode':app.GATEWAY,'base':'https://'+name.lower()+'.example/v1','key':key,'model':model,'models':[{'id':model},{'id':model+'-other'}],'catalog_base':'https://'+name.lower()+'.example/v1'}
                    one=a.store.save(None,profile('First','fake-card-key-a','model-a'))
                    two=a.store.save(None,profile('Second','fake-card-key-b','model-b'))
                    a.update_platform_menu(); a.render_platforms(); a.update()
                    self.assertEqual(len(a.card_models),2)
                    def texts(w):
                        result=[]
                        if isinstance(w,app.ctk.CTkLabel): result.append(w.cget('text'))
                        for child in w.winfo_children(): result.extend(texts(child))
                        return result
                    for key in ('fake-card-key-a','fake-card-key-b'):
                        self.assertNotIn(key,'\n'.join(texts(a.platform_grid)))
                    def wait_done():
                        deadline=time.monotonic()+20
                        while a.busy and time.monotonic()<deadline:
                            a.update(); time.sleep(.015)
                        self.assertFalse(a.busy)
                        a.update()
                    a.card_models[one].set('model-a-other')
                    before=config.read_bytes()
                    with patch.object(app,'probe',return_value={'reported':'mock'}) as probe:
                        a.card_action(one,False)
                        self.assertTrue(a.busy)
                        a.card_action(two,False) # ignored while busy
                        wait_done()
                        self.assertEqual(probe.call_count,1)
                        self.assertEqual(probe.call_args.args[:3],('https://first.example/v1','fake-card-key-a','model-a-other'))
                    self.assertEqual(config.read_bytes(),before)
                    self.assertIn('验证通过',a.card_statuses[one].cget('text'))
                    with patch.object(app,'probe',return_value={'reported':'mock'}) as probe:
                        a.card_action(two,True); wait_done()
                        self.assertEqual(probe.call_args.args[:3],('https://second.example/v1','fake-card-key-b','model-b'))
                    self.assertEqual(core.selected_config(core.read_config(config)[1]),('model-b',core.PROVIDER))
                    self.assertTrue(a.platforms_page.winfo_ismapped())
                    self.assertIn('切换成功',a.card_statuses[two].cget('text'))
                    before=config.read_bytes()
                    with patch.object(app,'probe',side_effect=RuntimeError('mock 401')):
                        a.card_action(one,True); wait_done()
                    self.assertEqual(config.read_bytes(),before)
                    self.assertIn('401',a.card_statuses[one].cget('text'))
                    for size in ('1180x820','1020x760'):
                        a.geometry(size); a.update()
                        for page in ('editor','platforms'):
                            a.show_page(page); a.update()
                            for b in a.buttons:
                                if not b.winfo_ismapped(): continue
                                x,y=b.winfo_rootx()-a.winfo_rootx(),b.winfo_rooty()-a.winfo_rooty()
                                self.assertGreaterEqual(x,0,b.cget('text'))
                                self.assertLessEqual(x+b.winfo_width(),a.winfo_width(),b.cget('text'))
                                self.assertGreaterEqual(y,0,b.cget('text'))
                                self.assertLessEqual(y+b.winfo_height(),a.winfo_height(),b.cget('text'))
                    a.edit_card(one); a.update()
                    self.assertTrue(a.editor_page.winfo_ismapped())
                    with patch.object(app.messagebox,'askyesno',return_value=True):
                        a.remove_card(two)
                    self.assertNotIn(two,a.store.data['platforms'])
                finally:
                    a.close()

if __name__=='__main__': unittest.main(verbosity=2)
