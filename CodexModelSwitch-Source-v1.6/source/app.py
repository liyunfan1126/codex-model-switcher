from __future__ import annotations
import json
import os
from pathlib import Path
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk
from diagnostics import Diagnostics, set_sink
from core import *
from connections import GATEWAY, ROUTER, CUSTOM, MODES, PlatformStore, connection_base, family_matches

ctk.set_appearance_mode('dark')
ctk.set_default_color_theme('blue')
BG, PANEL, CARD, BLUE, MUTED = '#10141e', '#181e2a', '#222b3a', '#537cf5', '#98a7bf'
FAMILIES = {'全部': '', 'Claude': 'anthropic/', 'GPT': 'openai/', 'Gemini': 'google/',
            'DeepSeek': 'deepseek/', 'Qwen': 'qwen/', 'Kimi': 'moonshotai/', 'GLM': 'z-ai/', 'MiniMax': 'minimax/'}

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title('Codex Model Switch 1.6 | 模型切换器')
        self.log = Diagnostics(data_path() / 'logs')
        set_sink(self.log)
        self.log_window = None
        self.log_version = -1
        self.log.write('启动 Codex Model Switch 1.6；日志不记录请求正文、密钥或凭据解密输出。')
        self.geometry('1180x820')
        self.minsize(1020, 760)
        self.configure(fg_color=BG)
        self.events = queue.Queue()
        self.busy = False
        self.models = []
        self.page = 0
        self.family = '全部'
        self.catalog_base = ''
        self.mode = GATEWAY
        self.platform_id = None
        self.platform_name = ''
        self.platform_drafts = {}
        self.store = None
        self.changing_connection = False
        self.selected = tk.StringVar()
        self.search = tk.StringVar()
        self.base = tk.StringVar()
        self.key = tk.StringVar()
        self.path = tk.StringVar(value=str(config_path()))
        self.buttons = []
        self.card_statuses = {}
        self.card_models = {}
        self.card_controls = []
        self.active_card = None
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.build_sidebar()
        self.build_main()
        self.build_platform_page()
        self.search.trace_add('write', lambda *_: self.filter_changed())
        self.base.trace_add('write', lambda *_: self.endpoint_changed())
        self.selected.trace_add('write', lambda *_: self.selection_changed())
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.after(80, self.pump)
        self.load_saved()
        self.log.add_secret(self.key.get())
        self.read_current()
        self.show_page('platforms')

    def label(self, parent, text, size=13, color='white', **kw):
        return ctk.CTkLabel(parent, text=text, font=('Microsoft YaHei UI', size), text_color=color, **kw)

    def button(self, parent, text, command, primary=False, **kw):
        b = ctk.CTkButton(parent, text=text, command=command, height=kw.pop('height', 36),
                          fg_color=BLUE if primary else CARD, hover_color='#3a5078',
                          font=('Microsoft YaHei UI', 13), **kw)
        self.buttons.append(b)
        return b

    def build_sidebar(self):
        side = ctk.CTkFrame(self, width=190, fg_color=PANEL, corner_radius=0)
        side.grid(row=0, column=0, sticky='nsew')
        side.grid_propagate(False)
        self.label(side, 'C / SWITCH', 23).pack(anchor='w', padx=24, pady=(30, 4))
        self.label(side, 'Codex 模型切换器', color=MUTED).pack(anchor='w', padx=24, pady=(0, 14))
        self.nav_platforms = self.button(side, '我的平台', lambda: self.show_page('platforms'), width=146)
        self.nav_platforms.pack(padx=18, pady=4)
        self.nav_editor = self.button(side, '平台设置 / 模型', lambda: self.show_page('editor'), width=146)
        self.nav_editor.pack(padx=18, pady=4)
        self.family_area = ctk.CTkFrame(side, fg_color='transparent')
        self.family_area.pack(fill='x', pady=(10, 0))
        self.label(self.family_area, '当前平台 · 模型分类', 12, MUTED).pack(anchor='w', padx=20, pady=(0, 6))
        self.family_buttons = {}
        for name in FAMILIES:
            b = self.button(self.family_area, name, lambda n=name: self.change_family(n), anchor='w', width=146, height=30)
            b.pack(padx=18, pady=2)
            self.family_buttons[name] = b
        self.label(side, 'Responses API\nWindows 密钥加密\n自动备份 · 可撤销', 12, MUTED, justify='left').pack(side='bottom', padx=20, pady=28, anchor='w')

    def build_main(self):
        main = ctk.CTkFrame(self, fg_color='transparent')
        self.editor_page = main
        main.grid(row=0, column=1, sticky='nsew', padx=28, pady=22)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(3, weight=1)
        head = ctk.CTkFrame(main, fg_color='transparent')
        head.grid(row=0, column=0, sticky='ew')
        self.label(head, '为 Codex 选择下一位搭档', 25).pack(anchor='w')
        self.current = self.label(head, '', 12, MUTED)
        self.current.pack(anchor='w', pady=(3, 15))
        platform_bar = ctk.CTkFrame(head, fg_color='transparent')
        platform_bar.pack(fill='x', pady=(0, 12))
        self.label(platform_bar, '已保存平台', color=MUTED).pack(side='left', padx=(0, 12))
        self.platform_menu = ctk.CTkOptionMenu(platform_bar, values=['暂无平台，请新增'], width=235, command=self.select_platform)
        self.platform_menu.pack(side='left', padx=(0, 8))
        self.button(platform_bar, '新增平台', self.new_platform, width=90).pack(side='left', padx=4)
        self.button(platform_bar, '重命名', self.rename_platform, width=80).pack(side='left', padx=4)
        self.button(platform_bar, '删除', self.delete_platform, width=65).pack(side='left', padx=4)
        settings = ctk.CTkFrame(main, fg_color=PANEL, corner_radius=12)
        settings.grid(row=1, column=0, sticky='ew')
        settings.grid_columnconfigure(1, weight=1)
        self.label(settings, '接入方式', color=MUTED).grid(row=0, column=0, padx=16, pady=(14, 6), sticky='w')
        self.provider = ctk.CTkOptionMenu(settings, values=MODES, width=290, command=self.provider_changed)
        self.provider.grid(row=0, column=1, padx=8, pady=(14, 6), sticky='w')
        connection_actions = ctk.CTkFrame(settings, fg_color='transparent')
        connection_actions.grid(row=0, column=2, padx=16, pady=(14, 6))
        self.button(connection_actions, '保存接口', self.save_connection, width=90).pack(side='left', padx=(0, 8))
        self.button(connection_actions, '刷新模型', self.refresh, width=100).pack(side='left')
        self.label(settings, 'API 地址', color=MUTED).grid(row=1, column=0, padx=16, pady=6)
        self.base_entry = ctk.CTkEntry(settings, textvariable=self.base, height=34)
        self.base_entry.grid(row=1, column=1, columnspan=2, sticky='ew', padx=(8, 16), pady=6)
        self.label(settings, 'API Key', color=MUTED).grid(row=2, column=0, padx=16, pady=6)
        self.key_entry = ctk.CTkEntry(settings, textvariable=self.key, show='•', height=34, placeholder_text='输入当前服务商的 API Key')
        self.key_entry.grid(row=2, column=1, sticky='ew', padx=8, pady=6)
        self.show_key = ctk.CTkCheckBox(settings, text='显示', width=70, command=lambda: self.key_entry.configure(show='' if self.show_key.get() else '•'))
        self.show_key.grid(row=2, column=2, sticky='w', padx=16)
        self.connection_hint = self.label(settings, '', 11, MUTED, wraplength=700, justify='left')
        self.connection_hint.grid(row=3, column=0, columnspan=3, sticky='w', padx=16, pady=(2, 12))

        toolbar = ctk.CTkFrame(main, fg_color='transparent')
        toolbar.grid(row=2, column=0, sticky='ew', pady=(16, 8))
        toolbar.grid_columnconfigure(0, weight=1)
        ctk.CTkEntry(toolbar, textvariable=self.search, placeholder_text='搜索模型名称 / ID', height=35).grid(row=0, column=0, sticky='ew')
        self.catalog_note = self.label(toolbar, '', 11, MUTED)
        self.catalog_note.grid(row=0, column=1, padx=(14, 0))
        self.cards = ctk.CTkScrollableFrame(main, fg_color='transparent', corner_radius=0)
        self.cards.grid(row=3, column=0, sticky='nsew')
        self.cards.grid_columnconfigure((0, 1), weight=1)
        bottom = ctk.CTkFrame(main, fg_color='transparent')
        bottom.grid(row=4, column=0, sticky='ew', pady=(6, 0))
        bottom.grid_columnconfigure(0, weight=1)
        pager = ctk.CTkFrame(bottom, fg_color='transparent')
        pager.grid(row=0, column=0, sticky='ew')
        self.label(pager, '按上架时间排序 · 目录声明支持工具调用；实际可用性以验证为准', 11, MUTED).pack(side='left')
        self.button(pager, '下一页', lambda: self.turn_page(1), width=68).pack(side='right', padx=(6, 0))
        self.button(pager, '上一页', lambda: self.turn_page(-1), width=68).pack(side='right')
        self.page_label = self.label(pager, '', 11, MUTED)
        self.page_label.pack(side='right', padx=8)
        selection = ctk.CTkFrame(bottom, fg_color=PANEL)
        selection.grid(row=1, column=0, sticky='ew', pady=(10, 8))
        selection.grid_columnconfigure(1, weight=1)
        self.label(selection, '模型 ID', color=MUTED).grid(row=0, column=0, padx=14, pady=12)
        self.model_entry = ctk.CTkEntry(selection, textvariable=self.selected, height=36, placeholder_text='选择卡片，或手动输入模型 ID')
        self.model_entry.grid(row=0, column=1, padx=4, pady=12, sticky='ew')
        self.button(selection, '仅验证', lambda: self.switch(False), width=85).grid(row=0, column=2, padx=8)
        self.button(selection, '验证并一键切换', lambda: self.switch(True), True, width=150).grid(row=0, column=3, padx=(0, 14))
        self.status = self.label(bottom, '等待操作 · 验证会发起两次小额 API 请求，按服务商计费。', 12, MUTED, anchor='w', wraplength=840, justify='left')
        self.status.grid(row=2, column=0, sticky='ew', pady=(0, 6))
        foot = ctk.CTkFrame(bottom, fg_color='transparent')
        foot.grid(row=3, column=0, sticky='ew')
        self.button(foot, '恢复 Codex 默认', self.reset_default, width=145).pack(side='left', padx=(0, 8))
        self.button(foot, '恢复上次配置', self.restore, width=125).pack(side='left')
        self.button(foot, '配置文件位置', self.choose_path, width=120).pack(side='left', padx=8)
        self.button(foot, '重新读取状态', self.read_current, width=120).pack(side='left')
        self.button(foot, '操作日志', self.show_logs, width=90).pack(side='left', padx=8)
        self.label(bottom, '恢复默认：使用内置服务和默认模型，保留登录、历史任务与其他设置。切换后重启 Codex 并新建任务。', 11, MUTED).grid(row=4, column=0, sticky='w', pady=(7, 0))

    def build_platform_page(self):
        page = self.platforms_page = ctk.CTkFrame(self, fg_color='transparent')
        page.grid(row=0, column=1, sticky='nsew', padx=28, pady=22)
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(2, weight=1)
        head = ctk.CTkFrame(page, fg_color='transparent')
        head.grid(row=0, column=0, sticky='ew', pady=(0, 10))
        self.label(head, '我的平台', 27).pack(side='left')
        self.button(head, '+ 新增平台', self.new_platform, True, width=125).pack(side='right')
        self.label(page, '仅本机保存 · 每个平台独立管理\nKey 只保存在当前 Windows 用户的加密平台库中，不包含在安装包或源码包内。', 13, MUTED, justify='left', anchor='w', wraplength=760).grid(row=1, column=0, sticky='ew', pady=(0, 18))
        self.platform_grid = ctk.CTkScrollableFrame(page, fg_color='transparent')
        self.platform_grid.grid(row=2, column=0, sticky='nsew')
        self.platform_grid.grid_columnconfigure((0, 1), weight=1, uniform='platforms')
        self.platform_status = self.label(page, '选择卡片内的模型，即可验证或验证后切换。验证按服务商计费。', 12, MUTED, anchor='w', justify='left', wraplength=800)
        self.platform_status.grid(row=3, column=0, sticky='ew', pady=12)
        bar = ctk.CTkFrame(page, fg_color='transparent')
        bar.grid(row=4, column=0, sticky='ew')
        self.button(bar, '恢复 Codex 默认', self.reset_default, width=145).pack(side='left', padx=(0, 8))
        self.button(bar, '恢复上次配置', self.restore, width=125).pack(side='left', padx=(0, 8))
        self.button(bar, '操作日志', self.show_logs, width=100).pack(side='left')

    def show_page(self, page):
        if page == 'platforms':
            self.editor_page.grid_remove()
            self.platforms_page.grid()
            self.family_area.pack_forget()
            self.render_platforms()
        else:
            self.platforms_page.grid_remove()
            self.editor_page.grid()
            self.family_area.pack(fill='x', pady=(10, 0))
        self.nav_platforms.configure(fg_color=BLUE if page == 'platforms' else CARD)
        self.nav_editor.configure(fg_color=BLUE if page == 'editor' else CARD)

    def render_platforms(self):
        for child in self.platform_grid.winfo_children():
            child.destroy()
        self.buttons = [b for b in self.buttons if b.winfo_exists()]
        self.card_models = {}
        self.card_statuses = {}
        self.card_controls = []
        platforms = self.store.data['platforms'] if self.store else {}
        if not platforms:
            self.label(self.platform_grid, '还没有保存的平台\n点击“新增平台”，填写你自己的 API 地址和 Key。\n首次安装不会带入任何人的平台记录。', 16, MUTED, justify='center').grid(row=0, column=0, columnspan=2, pady=80, padx=12)
        for index, (ident, p) in enumerate(platforms.items()):
            tile = ctk.CTkFrame(self.platform_grid, fg_color=PANEL, corner_radius=14, height=285)
            tile.grid(row=index//2, column=index%2, sticky='nsew', padx=6, pady=7)
            tile.grid_columnconfigure(0, weight=1)
            self.label(tile, p['name'], 19, anchor='w', wraplength=300).grid(row=0, column=0, sticky='ew', padx=18, pady=(17, 4))
            # Never render credentials or URL userinfo/query strings on cards.
            host = urlsplit(p['base']).hostname or '自定义平台'
            self.label(tile, host + '\n密钥：已加密保存', 12, MUTED, anchor='w', justify='left', wraplength=300).grid(row=1, column=0, sticky='ew', padx=18, pady=(0, 12))
            ids = list(dict.fromkeys([p.get('model', '')] + [m['id'] for m in p.get('models', []) if isinstance(m, dict) and isinstance(m.get('id'), str)]))
            ids = [value for value in ids if value] or ['']
            var = tk.StringVar(value=p.get('model') or ids[0])
            self.card_models[ident] = var
            choice = ctk.CTkComboBox(tile, variable=var, values=ids, height=34)
            choice.grid(row=2, column=0, sticky='ew', padx=18, pady=(0, 10))
            self.card_controls.append(choice)
            actions = ctk.CTkFrame(tile, fg_color='transparent')
            actions.grid(row=3, column=0, sticky='ew', padx=18)
            actions.grid_columnconfigure((0,1),weight=1)
            self.button(actions, '一键验证', lambda k=ident:self.card_action(k, False), width=95).grid(row=0,column=0,sticky='ew',padx=(0,6))
            self.button(actions, '验证并切换', lambda k=ident:self.card_action(k, True), True,width=115).grid(row=0,column=1,sticky='ew')
            result = self.label(tile, '选择或输入模型 ID 后操作', 11, MUTED, wraplength=300, justify='left', anchor='w')
            result.grid(row=4,column=0,sticky='ew',padx=18,pady=(9,4))
            self.card_statuses[ident] = result
            manage = ctk.CTkFrame(tile, fg_color='transparent')
            manage.grid(row=5,column=0,sticky='ew',padx=18,pady=(2,15))
            self.button(manage, '编辑 / 刷新模型', lambda k=ident:self.edit_card(k),width=140,height=30).pack(side='left')
            self.button(manage, '删除', lambda k=ident:self.remove_card(k),width=65,height=30).pack(side='right')
        if self.busy:
            for b in self.buttons:
                b.configure(state='disabled')
            for w in self.card_controls:
                w.configure(state='disabled')

    def edit_card(self, ident):
        self.select_platform(self.store.data['platforms'][ident]['name'])
        self.show_page('editor')

    def remove_card(self, ident):
        if self.busy:
            return
        self.select_platform(self.store.data['platforms'][ident]['name'])
        self.delete_platform()
        self.render_platforms()

    def card_action(self, ident, apply):
        if self.busy:
            return
        model = self.card_models[ident].get().strip()
        if not model:
            self.set_status('请先在卡片中选择或输入模型 ID，或点击编辑刷新模型。', '#ffb47d')
            return
        if self.platform_id:
            self.platform_drafts[self.platform_id] = self.current_profile()
        saved = self.store.data['platforms'][ident]
        self.platform_id = ident
        self.platform_name = saved['name']
        self.platform_menu.set(self.platform_name)
        self.show_connection(saved)
        self.selected.set(model)
        self.active_card = ident
        self.switch(apply)

    def post(self, func, *args):
        self.events.put((func, args))

    def pump(self):
        while not self.events.empty():
            func, args = self.events.get()
            try:
                func(*args)
            except Exception as exc:
                self.report_callback_exception(type(exc), exc, exc.__traceback__)
        self.refresh_logs()
        self.after(80, self.pump)

    def set_status(self, text, color=MUTED):
        self.status.configure(text=text, text_color=color)
        self.platform_status.configure(text=text, text_color=color)
        card = self.card_statuses.get(self.active_card)
        if card and card.winfo_exists():
            card.configure(text=text, text_color=color)
        self.log.write(text, 'ERROR' if color == '#ffb47d' else 'INFO')

    def report_callback_exception(self, exc, value, tb):
        self.log.exception(value, '界面回调失败')
        if hasattr(self, 'status'):
            self.status.configure(text='界面操作失败，请查看操作日志。', text_color='#ffb47d')

    def show_logs(self):
        if self.log_window and self.log_window.winfo_exists():
            self.log_window.lift()
            return
        win = self.log_window = ctk.CTkToplevel(self)
        win.title('操作日志 · Codex Model Switch')
        win.geometry('900x540')
        win.minsize(650, 400)
        win.grid_columnconfigure(0, weight=1)
        win.grid_rowconfigure(1, weight=1)
        self.log_hint = self.label(win, '', 12, MUTED, anchor='w', wraplength=800)
        self.log_hint.grid(row=0, column=0, sticky='ew', padx=16, pady=12)
        self.log_text = ctk.CTkTextbox(win, font=('Consolas', 12), wrap='word')
        self.log_text.grid(row=1, column=0, sticky='nsew', padx=16)
        bar = ctk.CTkFrame(win, fg_color='transparent')
        bar.grid(row=2, column=0, sticky='ew', padx=16, pady=12)
        for title, action in [('复制所示日志', self.copy_logs), ('导出所示日志', self.export_logs), ('打开日志目录', self.open_log_folder)]:
            ctk.CTkButton(bar, text=title, command=action, width=145).pack(side='left', padx=(0, 8))
        self.log_version = -1
        self.refresh_logs()

    def refresh_logs(self):
        if not self.log_window or not self.log_window.winfo_exists():
            return
        self.log_hint.configure(text=('磁盘日志写入失败；以下内存日志仍可复制、导出。' if self.log.disk_error else '自动写入：' + str(self.log.path)) + '\n显示当前会话最近 2000 条；日志包含操作时间、结果和错误位置。')
        if self.log_version == self.log.version:
            return
        self.log_text.configure(state='normal')
        self.log_text.delete('1.0', 'end')
        self.log_text.insert('1.0', self.log.snapshot())
        self.log_text.see('end')
        self.log_text.configure(state='disabled')
        self.log_version = self.log.version

    def copy_logs(self):
        self.clipboard_clear()
        self.clipboard_append(self.log.snapshot())
        self.set_status('已复制当前会话所示日志。')

    def export_logs(self):
        target = filedialog.asksaveasfilename(parent=self.log_window, title='导出所示日志', defaultextension='.log', initialfile='CodexModelSwitch-' + time.strftime('%Y%m%d-%H%M%S') + '.log', filetypes=[('日志', '*.log'), ('文本', '*.txt')])
        if target:
            try:
                atomic_write(Path(target), self.log.snapshot().encode('utf-8'))
                self.set_status('日志导出成功。')
            except OSError as exc:
                self.log.exception(exc, '日志导出失败')
                self.set_status('日志导出失败，请检查目标目录权限。', '#ffb47d')

    def open_log_folder(self):
        try:
            os.startfile(str(self.log.path.parent))
        except OSError as exc:
            self.log.exception(exc, '无法打开日志目录')
            self.set_status('无法打开日志目录，可使用“导出所示日志”。', '#ffb47d')

    def set_busy(self, value):
        self.busy = value
        self.buttons = [b for b in self.buttons if b.winfo_exists()]
        for b in self.buttons:
            b.configure(state='disabled' if value else 'normal')
        for w in (self.base_entry, self.key_entry, self.model_entry, self.provider, self.platform_menu):
            w.configure(state='disabled' if value else 'normal')
        if not value and self.mode == ROUTER:
            self.base_entry.configure(state='disabled')
        for widget in self.card_controls:
            if widget.winfo_exists():
                widget.configure(state='disabled' if value else 'normal')
        if not value:
            self.active_card = None

    def background(self, work, done, operation='操作'):
        if self.busy:
            return
        self.set_busy(True)
        started = time.monotonic()
        self.log.write(operation + '：开始')
        def run():
            try:
                result = work()
                self.log.write(f'{operation}：后台处理完成，耗时 {time.monotonic() - started:.2f} 秒')
                self.post(done, result)
            except Exception as exc:
                # Never expose response bodies, credentials, or auth command output.
                safe = str(exc) if isinstance(exc, (RuntimeError, ValueError)) else f'{type(exc).__name__}：操作失败，请检查网络、配置格式或文件权限。'
                for secret in [self.active_key] if hasattr(self, 'active_key') else []:
                    if secret:
                        safe = safe.replace(secret, '[已隐藏]')
                self.post(self.set_status, '未完成：' + safe, '#ffb47d')
                self.log.exception(exc, f'{operation}失败，耗时 {time.monotonic() - started:.2f} 秒：{safe}')
            finally:
                self.post(self.set_busy, False)
        threading.Thread(target=run, daemon=True).start()

    def load_catalog(self):
        bundled = Path(getattr(sys, '_MEIPASS', Path(__file__).parent)) / 'catalog.json'
        path = data_path() / 'catalog.json'
        try:
            data = json.loads((path if path.exists() else bundled).read_text(encoding='utf-8'))
            self.models = data['data']
            self.catalog_note.configure(text='目录快照 ' + data.get('fetched_at', ''))
        except Exception:
            self.catalog_note.configure(text='请刷新模型目录')
        self.render_cards()

    def load_saved(self):
        try:
            self.store = PlatformStore(data_path())
            self.update_platform_menu()
            ident = self.store.data['active'] or next(iter(self.store.data['platforms']), None)
            self.activate_platform(ident)
        except Exception as exc:
            self.log.exception(exc, '读取保存的接口失败')
            self.set_status('未能读取保存的接口，请重新填写地址和 Key。', '#ffb47d')

    def current_profile(self):
        return {'name': self.platform_name, 'mode': self.mode, 'base': self.base.get().strip(), 'key': self.key.get().strip(),
                'model': self.selected.get().strip(), 'models': self.models, 'catalog_base': self.catalog_base}

    def update_platform_menu(self):
        self.platform_names = {p['name']: ident for ident, p in self.store.data['platforms'].items()}
        self.platform_menu.configure(values=list(self.platform_names) or ['暂无平台，请新增'])

    def activate_platform(self, ident):
        self.platform_id = ident
        draft = self.platform_drafts.get(ident, self.store.data['platforms'].get(ident, {}))
        self.platform_name = draft.get('name', '')
        self.platform_menu.set(self.platform_name or '暂无平台，请新增')
        self.show_connection(draft)

    def show_connection(self, draft):
        mode = draft.get('mode', GATEWAY)
        self.changing_connection = True
        self.mode = mode
        self.provider.set(mode)
        self.base.set(OPENROUTER if mode == ROUTER else draft.get('base', ''))
        self.key.set(draft.get('key', ''))
        self.log.add_secret(self.key.get())
        self.selected.set(draft.get('model', ''))
        self.changing_connection = False
        self.models = draft.get('models', [])
        self.catalog_base = draft.get('catalog_base', '')
        self.family = '全部'
        self.search.set('')
        self.base_entry.configure(state='disabled' if mode == ROUTER else 'normal')
        self.connection_hint.configure(text='每个平台独立保存地址、Key 和模型。修改后点击“保存接口”；新增平台不会覆盖已有平台。')
        if mode == ROUTER and not self.models:
            self.catalog_base = OPENROUTER
            self.load_catalog()
        else:
            self.catalog_note.configure(text='已载入此平台模型缓存' if self.models else '请刷新当前接口模型')
            self.filter_changed()

    def select_platform(self, name):
        ident = self.platform_names.get(name)
        if ident is None:
            return
        if self.platform_id:
            self.platform_drafts[self.platform_id] = self.current_profile()
        try:
            self.store.activate(ident)
            self.activate_platform(ident)
            self.set_status('已载入平台“' + name + '”的地址、Key 和模型。选择模型后点击“验证并一键切换”。')
        except Exception as exc:
            self.log.exception(exc, '选择平台失败')
            self.set_status('无法切换平台，请检查配置文件权限。', '#ffb47d')

    def new_platform(self):
        name = ctk.CTkInputDialog(text='为新平台命名（例如：公司中转、个人平台、OpenRouter）', title='新增平台').get_input()
        if not name or not name.strip():
            return
        name = name.strip()
        if len(name) > 48 or any(n.casefold() == name.casefold() for n in self.platform_names):
            self.set_status('名称过长或已存在，请换一个平台名称。', '#ffb47d')
            return
        if self.platform_id:
            self.platform_drafts[self.platform_id] = self.current_profile()
        self.platform_id = None
        self.platform_name = name
        self.platform_menu.set(name + '（待保存）')
        self.show_connection({'mode': ROUTER if name.casefold() == 'openrouter' else GATEWAY})
        self.show_page('editor')
        self.set_status('填写新平台的地址和 Key，然后点击“保存接口”。')

    def rename_platform(self):
        if not self.platform_id:
            self.set_status('请先保存平台，再重命名。')
            return
        name = ctk.CTkInputDialog(text='请输入新的平台名称', title='重命名平台').get_input()
        if not name:
            return
        try:
            p = dict(self.store.data['platforms'][self.platform_id], name=name)
            self.store.save(self.platform_id, p)
            self.platform_name = p['name'].strip()
            if self.platform_id in self.platform_drafts:
                self.platform_drafts[self.platform_id]['name'] = self.platform_name
            self.update_platform_menu()
            self.platform_menu.set(self.platform_name)
            self.render_platforms()
            self.set_status('平台名称已更新。')
        except Exception as exc:
            self.log.exception(exc, '重命名失败')
            self.set_status(str(exc) if isinstance(exc, ValueError) else '重命名失败，请检查文件权限。', '#ffb47d')

    def delete_platform(self):
        if not self.platform_id:
            self.set_status('当前没有已保存的平台可删除。')
            return
        if not messagebox.askyesno('删除平台', f'删除“{self.platform_name}”的已保存接口与模型缓存？\n\n不会修改正在使用的 Codex 配置或用于回滚的备份。'):
            return
        try:
            self.store.delete(self.platform_id)
            self.platform_drafts.pop(self.platform_id, None)
            self.update_platform_menu()
            self.activate_platform(self.store.data['active'])
            self.render_platforms()
            self.set_status('平台记录已删除；当前 Codex 配置未修改。')
        except Exception as exc:
            self.log.exception(exc, '删除平台失败')
            self.set_status('删除失败，原平台记录保留。', '#ffb47d')

    def save_connection(self, silent=False):
        try:
            self.log.add_secret(self.key.get().strip())
            connection_base(self.mode, self.base.get())
            if not self.key.get().strip():
                raise ValueError('请输入当前平台的 API Key。')
            if not self.platform_name:
                self.platform_name = urlsplit(self.base.get()).hostname or '我的平台'
            self.platform_id = self.store.save(self.platform_id, self.current_profile())
            self.platform_drafts.pop(self.platform_id, None)
            self.update_platform_menu()
            self.platform_menu.set(self.platform_name)
            self.render_platforms()
            if not silent:
                self.set_status('接口地址、Key 和模型已加密保存；尚未验证可用性。', '#83ddb1')
        except Exception as exc:
            self.log.exception(exc, '保存接口失败')
            self.set_status('接口保存失败，请检查地址、Key 和目录权限。', '#ffb47d')

    def provider_changed(self, value):
        if value == self.mode:
            return
        self.show_connection({'mode': value})
        self.set_status('已更改当前平台的接入方式。填写地址与 Key 后保存；如需保留原接口，请使用“新增平台”。')

    def endpoint_changed(self):
        if self.changing_connection:
            return
        # Prevent silently forwarding a previously entered key to another host.
        self.key.set('')
        self.selected.set('')
        self.models = []
        self.catalog_base = ''
        self.catalog_note.configure(text='地址已变更，请刷新模型')
        self.filter_changed()

    def selection_changed(self):
        if not self.busy:
            self.set_status('待验证 · 验证会产生两次小额 API 调用；通过后才写入配置。')

    def change_family(self, name):
        self.family = name
        self.filter_changed()

    def filter_changed(self):
        self.page = 0
        self.render_cards()

    def filtered(self):
        if self.base.get().rstrip('/') != self.catalog_base:
            return []
        q = self.search.get().lower().strip()
        def eligible(m):
            if ':batch' in m['id'] or not family_matches(m, self.family):
                return False
            if self.catalog_base == OPENROUTER:
                if 'tools' not in m.get('supported_parameters', []):
                    return False
                if m.get('architecture', {}).get('output_modalities', ['text']) != ['text']:
                    return False
            return q in (m['id'] + ' ' + m.get('name', '')).lower()
        return sorted([m for m in self.models if eligible(m)], key=lambda m: m.get('created', 0), reverse=True)

    def render_cards(self):
        for child in self.cards.winfo_children():
            child.destroy()
        for name, b in self.family_buttons.items():
            b.configure(fg_color=BLUE if name == self.family else CARD)
        all_models = self.filtered()
        pages = max(1, (len(all_models) + 19) // 20)
        self.page = max(0, min(self.page, pages - 1))
        self.page_label.configure(text=f'{self.page + 1}/{pages} · {len(all_models)} 个')
        if not all_models:
            self.label(self.cards, '没有匹配模型\n可刷新当前接口目录，或在下方手动填写模型 ID。', 14, MUTED).grid(row=0, column=0, columnspan=2, pady=30)
        for i, m in enumerate(all_models[self.page * 20: self.page * 20 + 20]):
            card = ctk.CTkFrame(self.cards, fg_color=CARD, corner_radius=10)
            card.grid(row=i // 2, column=i % 2, sticky='nsew', padx=4, pady=5)
            name = m.get('name', m['id'])
            title = self.label(card, name[:44], 14, anchor='w')
            title.pack(fill='x', padx=14, pady=(12, 2))
            ident = self.label(card, m['id'][:55], 11, MUTED, anchor='w')
            ident.pack(fill='x', padx=14)
            date = time.strftime('%Y-%m-%d', time.localtime(m.get('created', 0))) if m.get('created') else '自定义目录'
            context = m.get('context_length')
            details = date + (f'  ·  {context // 1000:,}K 上下文' if context else '')
            meta = self.label(card, details, 11, '#b6c5df', anchor='w')
            meta.pack(fill='x', padx=14, pady=(5, 12))
            for widget in (card, title, ident, meta):
                widget.bind('<Button-1>', lambda e, model=m['id']: self.pick(model))

    def pick(self, model):
        if not self.busy:
            self.selected.set(model)
            self.set_status('已选择 ' + model + ' · 点击“验证并一键切换”应用。')

    def turn_page(self, direction):
        self.page += direction
        self.render_cards()

    def refresh(self):
        base, key = self.base.get(), self.key.get().strip()
        self.log.add_secret(key)
        self.active_key = key
        self.set_status('正在从当前服务商获取最新模型目录…')
        def work():
            normalized = connection_base(self.mode, base)
            models = fetch_models(normalized, key)
            if normalized == OPENROUTER:
                atomic_write(data_path() / 'catalog.json', json.dumps({'data': models, 'fetched_at': time.strftime('%Y-%m-%d %H:%M')}, ensure_ascii=False).encode('utf-8'))
            return normalized, models
        def done(result):
            self.catalog_base, self.models = result
            self.catalog_note.configure(text='刚刚更新 ' + time.strftime('%H:%M'))
            self.filter_changed()
            self.set_status('模型目录已更新。目录可见不代表账户一定有调用权限。', '#83ddb1')
            if self.platform_id:
                saved = self.store.data['platforms'][self.platform_id]
                if saved['base'] == self.catalog_base and saved['key'] == key:
                    try:
                        self.store.save(self.platform_id, dict(saved, models=self.models, catalog_base=self.catalog_base))
                        self.log.write('当前平台模型目录已缓存，下次选择平台可直接使用')
                    except Exception as exc:
                        self.log.exception(exc, '模型目录缓存保存失败')
        self.background(work, done, '刷新模型目录')

    def switch(self, apply):
        base, key, model, path = self.base.get(), self.key.get().strip(), self.selected.get().strip(), self.path.get()
        self.log.add_secret(key)
        self.active_key = key
        def work():
            connection_base(self.mode, base)
            read_config(path)  # Fail before billable calls if the local file is malformed.
            result = probe(base, key, model, lambda msg: self.post(self.set_status, msg))
            if apply:
                self.post(self.set_status, 'API 已通过，正在加密保存密钥、备份并写入配置…')
                journal = apply_config(path, base, model, key)
                record = json.loads(Path(journal).read_text())
                try:
                    atomic_write(data_path() / 'last.json', json.dumps({'base': normalize_url(base), 'model': model, 'credential': record['credential']}).encode())
                except OSError:
                    result['save_warning'] = True
            return result
        def done(result):
            self.read_current()
            if apply:
                self.save_connection(silent=True)
                self.set_status('配置切换成功 · API 三项验证通过。桌面会话尚未验证：请完整退出 Codex，重新打开并新建任务。', '#83ddb1')
                messagebox.showinfo('配置切换成功', f'模型：{model}\nAPI 报告：{result["reported"]}\n\n✓ 流式响应、工具调用及续写通过\n✓ 配置已备份、写入并回读确认\n\n下一步：完整退出并重新打开 Codex，新建任务。\n已有任务、项目配置或组织策略可能覆盖默认模型。\n本程序尚未验证 Codex 桌面会话实际使用的模型。')
            else:
                self.set_status('API 验证通过 · 流式响应 / 工具调用 / 续写正常。未修改 Codex 配置。', '#83ddb1')
        self.background(work, done, '验证并切换' if apply else '验证 API')

    def read_current(self):
        try:
            _, d = read_config(self.path.get())
            model, provider = selected_config(d)
            self.current.configure(text=f'配置中：{model}  /  {provider}    ·    桌面运行状态未验证')
            self.log.write(f'读取配置成功：model={model}；provider={provider}')
        except Exception as exc:
            self.current.configure(text='无法读取配置，请检查文件位置和 TOML 格式。')
            self.log.exception(exc, '读取配置失败')

    def choose_path(self):
        path = filedialog.askopenfilename(title='选择 Codex config.toml', initialdir=str(Path(self.path.get()).parent), filetypes=[('TOML 配置', '*.toml')])
        if path:
            self.path.set(path)
            self.read_current()
            self.set_status('当前配置文件：' + path)

    def restore(self):
        path = self.path.get()
        def done(_):
            self.read_current()
            self.set_status('已撤销上次切换，保留其他新增设置。请重新打开 Codex 并新建任务。', '#83ddb1')
        self.background(lambda: restore_config(path), done, '恢复上次配置')

    def reset_default(self):
        path = self.path.get()
        self.set_status('正在备份并恢复 Codex 默认模型配置…')
        def done(changed):
            self.read_current()
            self.selected.set('')
            self.set_status(('已恢复 Codex 默认模型配置' if changed else '当前已使用 Codex 默认模型配置') + ' · 请重启 Codex 并新建任务。桌面会话尚未验证。', '#83ddb1')
            messagebox.showinfo('Codex 默认配置',
                '已使用 Codex 内置 OpenAI 服务，模型由 Codex 自动选择。\n\n'
                '登录信息、历史任务、插件和项目设置均保留。\n'
                + ('恢复前已备份，可用“恢复上次配置”撤销。\n' if changed else '没有需要修改的配置。\n')
                + '\n请完整退出并重新打开 Codex，再新建任务。\n'
                '项目配置、组织策略或启动参数仍可能覆盖默认选择。')
        self.background(lambda: reset_codex_default(path), done, '恢复 Codex 默认')

    def close(self):
        if self.busy:
            self.set_status('正在执行操作，请等待结果后关闭。', '#ffb47d')
            return
        self.log.write('程序正常关闭')
        self.log.close()
        set_sink(None)
        self.destroy()

if __name__ == '__main__':
    App().mainloop()
