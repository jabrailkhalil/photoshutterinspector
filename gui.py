#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PhotoShutterInspector — GUI версия с drag&drop.
"""

import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext
import threading
from pathlib import Path
from photoshutterinspector import PhotoShutterInspector, format_analysis_pretty, format_comparison_pretty


class PhotoShutterGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("📷 PhotoShutterInspector")
        self.root.geometry("900x700")
        self.root.configure(bg='#1e1e1e')
        
        self.inspector = None
        self.init_inspector()
        self.create_widgets()
    
    def init_inspector(self):
        try:
            self.inspector = PhotoShutterInspector()
            self.exiftool_status = f"✅ ExifTool {self.inspector.exiftool_version}"
        except RuntimeError as e:
            self.inspector = None
            self.exiftool_status = f"❌ {str(e)}"
    
    def create_widgets(self):
        # Header
        header = ttk.Frame(self.root)
        header.pack(fill='x', padx=20, pady=10)
        ttk.Label(header, text="📷 PhotoShutterInspector", font=('Consolas', 14, 'bold')).pack(side='left')
        ttk.Label(header, text=self.exiftool_status).pack(side='right')
        
        # Warning
        ttk.Label(self.root, text="⚠️ Для Canon shutter count часто НЕ записывается в файл!", foreground='#ff6b6b').pack(padx=20)
        
        # Buttons
        btn = ttk.Frame(self.root)
        btn.pack(fill='x', padx=20, pady=10)
        ttk.Button(btn, text="📁 Файл", command=self.select_file).pack(side='left', padx=5)
        ttk.Button(btn, text="📂 Папка", command=self.select_folder).pack(side='left', padx=5)
        ttk.Button(btn, text="🔍 Сравнить", command=self.compare_files).pack(side='left', padx=5)
        ttk.Button(btn, text="🗑️ Очистить", command=self.clear).pack(side='right')
        
        # Output
        self.output = scrolledtext.ScrolledText(self.root, font=('Consolas', 10), bg='#2d2d2d', fg='#d4d4d4')
        self.output.pack(fill='both', expand=True, padx=20, pady=10)
    
    def select_file(self):
        path = filedialog.askopenfilename(filetypes=[("Images", "*.jpg *.jpeg *.cr2 *.cr3 *.nef *.arw")])
        if path and self.inspector:
            threading.Thread(target=lambda: self.log(format_analysis_pretty(self.inspector.analyze_file(path))), daemon=True).start()
    
    def select_folder(self):
        path = filedialog.askdirectory()
        if path and self.inspector:
            def run():
                for a in self.inspector.analyze_directory(path):
                    self.log(format_analysis_pretty(a))
            threading.Thread(target=run, daemon=True).start()
    
    def compare_files(self):
        f1 = filedialog.askopenfilename(title="Первый файл")
        f2 = filedialog.askopenfilename(title="Второй файл") if f1 else None
        if f1 and f2 and self.inspector:
            threading.Thread(target=lambda: self.log(format_comparison_pretty(self.inspector.compare_files(f1, f2))), daemon=True).start()
    
    def log(self, msg):
        self.root.after(0, lambda: (self.output.insert('end', msg + "\n\n"), self.output.see('end')))
    
    def clear(self):
        self.output.delete('1.0', 'end')


if __name__ == '__main__':
    root = tk.Tk()
    PhotoShutterGUI(root)
    root.mainloop()
