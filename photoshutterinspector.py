#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PhotoShutterInspector — Честный анализатор EXIF для проверки пробега камеры.

ВАЖНОЕ ОГРАНИЧЕНИЕ:
Для многих камер Canon (включая EOS 200D, 600D, 700D и др.) shutter count 
НЕ ЗАПИСЫВАЕТСЯ в EXIF/RAW файлы. В таких случаях определить точный пробег 
по файлу НЕВОЗМОЖНО — требуется подключение камеры к ПК или сервисная диагностика.

Автор: PhotoShutterInspector Team
Лицензия: MIT
"""

import subprocess
import json
import sys
import os
import re
import csv
import argparse
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Any, Tuple
from dataclasses import dataclass, asdict, field
from enum import Enum


class VerificationResult(Enum):
    """Результат проверки сравнения двух файлов."""
    LIKELY_SAME_CAMERA = "LIKELY_SAME_CAMERA"
    INCONCLUSIVE = "INCONCLUSIVE"
    SUSPICIOUS = "SUSPICIOUS"


@dataclass
class FileAnalysis:
    """Результат анализа одного файла."""
    file_name: str
    file_path: str
    file_type: str  # Расширение файла
    file_size_bytes: int
    
    # Реальный тип файла (определяется по содержимому)
    real_file_type: Optional[str] = None
    mime_type: Optional[str] = None
    file_type_mismatch: bool = False  # Если расширение не соответствует содержимому
    
    # Основные данные камеры
    camera_make: Optional[str] = None
    camera_model: Optional[str] = None
    lens_model: Optional[str] = None
    serial_number: Optional[str] = None
    internal_serial: Optional[str] = None
    firmware: Optional[str] = None
    
    # Дата и время
    datetime_original: Optional[str] = None
    datetime_digitized: Optional[str] = None
    file_modify_date: Optional[str] = None
    
    # Пробег затвора (главное!)
    shutter_count: Optional[int] = None
    shutter_count_source: str = "none"
    shutter_count_present: bool = False
    
    # Косвенные данные (НЕ являются пробегом!)
    file_number_hint: Optional[int] = None
    file_number_warning: str = "Номер файла НЕ равен пробегу затвора; может сбрасываться, зависит от карты/настроек"
    directory_number: Optional[int] = None
    image_unique_id: Optional[str] = None
    
    # Детектор обработки
    software: Optional[str] = None
    processing_software: Optional[str] = None
    not_out_of_camera: bool = False
    editing_detected_warning: Optional[str] = None
    
    # Дополнительные технические данные
    iso: Optional[int] = None
    aperture: Optional[str] = None
    shutter_speed: Optional[str] = None
    focal_length: Optional[str] = None
    image_width: Optional[int] = None
    image_height: Optional[int] = None
    
    # Целостность EXIF
    exif_integrity_notes: List[str] = field(default_factory=list)
    
    # Ошибки при анализе
    errors: List[str] = field(default_factory=list)
    
    # Сырые данные ExifTool (опционально)
    raw_exif: Optional[Dict] = None


@dataclass
class ComparisonResult:
    """Результат сравнения двух файлов."""
    file1: str
    file2: str
    verdict: VerificationResult
    reasons: List[str]
    same_camera_model: bool = False
    same_serial_number: Optional[bool] = None
    same_firmware: Optional[bool] = None
    time_sequence_valid: Optional[bool] = None
    file_number_sequence_valid: Optional[bool] = None
    time_difference_seconds: Optional[float] = None


class PhotoShutterInspector:
    """Главный класс для анализа файлов."""
    
    # Известные редакторы (файл вероятно модифицирован)
    KNOWN_EDITORS = [
        'lightroom', 'photoshop', 'adobe', 'camera raw',
        'capture one', 'dxo', 'luminar', 'affinity',
        'gimp', 'darktable', 'rawtherapee',
        'snapseed', 'vsco', 'instagram', 'telegram',
        'whatsapp', 'facebook', 'vkontakte', 'vk',
        'messenger', 'viber', 'signal'
    ]
    
    # Теги для поиска shutter count
    SHUTTER_COUNT_TAGS = [
        # Canon
        'ShutterCount', 'ImageCount', 'ShutterCounter',
        'Canon:ShutterCount', 'Canon:ImageCount',
        'MakerNotes:ShutterCount', 'MakerNotes:ImageCount',
        # Nikon
        'ShutterCount', 'Nikon:ShutterCount',
        # Sony  
        'ImageCount', 'ReleaseMode2', 'Sony:ImageCount',
        # Pentax
        'ShutterCount', 'Pentax:ShutterCount',
        # Generic
        'ActuationCount', 'ImageNumber'
    ]
    
    SUPPORTED_EXTENSIONS = {'.jpg', '.jpeg', '.cr2', '.cr3', '.nef', '.arw', '.orf', '.rw2', '.dng'}
    
    def __init__(self, exiftool_path: str = "exiftool"):
        """
        Инициализация инспектора.
        
        Args:
            exiftool_path: Путь к исполняемому файлу exiftool
        """
        self.exiftool_path = exiftool_path
        self._verify_exiftool()
    
    def _verify_exiftool(self) -> None:
        """Проверка доступности ExifTool."""
        try:
            result = subprocess.run(
                [self.exiftool_path, '-ver'],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                raise RuntimeError(f"ExifTool returned error: {result.stderr}")
            self.exiftool_version = result.stdout.strip()
        except FileNotFoundError:
            raise RuntimeError(
                "ExifTool не найден! Установите его:\n"
                "  Windows: скачайте с https://exiftool.org/ и добавьте в PATH\n"
                "  Linux: sudo apt install libimage-exiftool-perl\n"
                "  macOS: brew install exiftool"
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("ExifTool не отвечает (timeout)")
    
    def _run_exiftool(self, file_path: str) -> Dict[str, Any]:
        """
        Запуск ExifTool и получение всех метаданных.
        
        Args:
            file_path: Путь к файлу
            
        Returns:
            Словарь с метаданными
        """
        try:
            # -j: JSON output
            # -G: Group names
            # -a: Allow duplicate tags
            # -u: Unknown tags
            # -n: Numeric values
            result = subprocess.run(
                [self.exiftool_path, '-j', '-G', '-a', '-u', '-n', file_path],
                capture_output=True, text=True, timeout=30,
                encoding='utf-8', errors='replace'
            )
            
            if result.returncode != 0 and not result.stdout:
                raise RuntimeError(f"ExifTool error: {result.stderr}")
            
            data = json.loads(result.stdout)
            return data[0] if data else {}
            
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"ExifTool timeout for {file_path}")
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Failed to parse ExifTool JSON: {e}")
    
    def _get_tag_value(self, exif: Dict, *tag_names: str) -> Optional[Any]:
        """Получить значение тега по списку возможных имён."""
        for tag in tag_names:
            # Прямой поиск
            if tag in exif:
                return exif[tag]
            # Поиск с группой (например "EXIF:Make")
            for key, value in exif.items():
                if key.endswith(':' + tag) or key == tag:
                    return value
        return None
    
    def _extract_file_number(self, filename: str) -> Optional[int]:
        """Извлечь номер файла из имени (IMG_1234.CR2 -> 1234)."""
        # Паттерны: IMG_1234, DSC_1234, _MG_1234, etc.
        patterns = [
            r'(?:IMG|DSC|_MG|_DSC)_?(\d+)',
            r'(\d{4,})\.(?:jpg|jpeg|cr2|cr3|nef|arw)',
        ]
        for pattern in patterns:
            match = re.search(pattern, filename, re.IGNORECASE)
            if match:
                return int(match.group(1))
        return None
    
    def _check_editing_software(self, software: Optional[str], processing: Optional[str]) -> Tuple[bool, Optional[str]]:
        """Проверить, был ли файл обработан редактором."""
        all_software = ' '.join(filter(None, [software, processing])).lower()
        
        for editor in self.KNOWN_EDITORS:
            if editor in all_software:
                return True, f"Обнаружен редактор/платформа: {editor.title()}. Метаданные могут быть изменены или удалены."
        
        return False, None
    
    def _find_shutter_count(self, exif: Dict) -> Tuple[Optional[int], str]:
        """
        Попытаться найти shutter count в метаданных.
        
        Returns:
            (shutter_count или None, источник тега)
        """
        # Прямой поиск по известным тегам
        for tag_pattern in self.SHUTTER_COUNT_TAGS:
            for key, value in exif.items():
                # Проверяем ключ (с учётом групп)
                key_lower = key.lower()
                tag_lower = tag_pattern.lower()
                
                if tag_lower in key_lower or key_lower.endswith(':' + tag_lower.split(':')[-1]):
                    if isinstance(value, (int, float)) and value > 0:
                        return int(value), key
                    elif isinstance(value, str) and value.isdigit():
                        return int(value), key
        
        return None, "none"
    
    def analyze_file(self, file_path: str, include_raw_exif: bool = False) -> FileAnalysis:
        """
        Анализ одного файла.
        
        Args:
            file_path: Путь к файлу
            include_raw_exif: Включить сырые данные ExifTool в результат
            
        Returns:
            Результат анализа
        """
        path = Path(file_path)
        
        # Базовая информация
        analysis = FileAnalysis(
            file_name=path.name,
            file_path=str(path.absolute()),
            file_type=path.suffix.lower().lstrip('.'),
            file_size_bytes=path.stat().st_size if path.exists() else 0
        )
        
        # Проверка расширения
        if path.suffix.lower() not in self.SUPPORTED_EXTENSIONS:
            analysis.errors.append(f"Неподдерживаемый тип файла: {path.suffix}")
            return analysis
        
        try:
            exif = self._run_exiftool(str(path))
        except Exception as e:
            analysis.errors.append(f"Ошибка чтения EXIF: {str(e)}")
            return analysis
        
        if include_raw_exif:
            analysis.raw_exif = exif
        
        # === Определение реального типа файла ===
        analysis.real_file_type = self._get_tag_value(exif, 'FileType', 'File:FileType')
        analysis.mime_type = self._get_tag_value(exif, 'MIMEType', 'File:MIMEType')
        
        # Проверка на несоответствие расширения и реального типа
        expected_types = {
            'cr2': ['CR2'],
            'cr3': ['CR3'],
            'jpg': ['JPEG', 'JPG'],
            'jpeg': ['JPEG', 'JPG'],
            'nef': ['NEF'],
            'arw': ['ARW'],
            'orf': ['ORF'],
            'rw2': ['RW2'],
            'dng': ['DNG'],
        }
        ext = analysis.file_type.lower()
        if ext in expected_types:
            if analysis.real_file_type and analysis.real_file_type.upper() not in expected_types[ext]:
                analysis.file_type_mismatch = True
                analysis.errors.append(
                    f"🚨 ВНИМАНИЕ: Расширение файла ({ext.upper()}) НЕ соответствует реальному типу ({analysis.real_file_type})! "
                    f"Это не настоящий {ext.upper()} файл."
                )
                analysis.exif_integrity_notes.append(
                    f"Файл имеет расширение .{ext}, но на самом деле это {analysis.real_file_type} ({analysis.mime_type})"
                )
        
        # === Основные данные камеры ===
        analysis.camera_make = self._get_tag_value(exif, 'Make', 'EXIF:Make')
        analysis.camera_model = self._get_tag_value(exif, 'Model', 'EXIF:Model', 'Camera Model Name')
        analysis.lens_model = self._get_tag_value(exif, 'LensModel', 'Lens', 'LensType', 'EXIF:LensModel')
        analysis.serial_number = self._get_tag_value(exif, 
            'SerialNumber', 'CameraSerialNumber', 'InternalSerialNumber',
            'Canon:SerialNumber', 'EXIF:SerialNumber'
        )
        analysis.internal_serial = self._get_tag_value(exif, 'InternalSerialNumber', 'Canon:InternalSerialNumber')
        analysis.firmware = self._get_tag_value(exif, 'Firmware', 'FirmwareVersion', 'Software')
        
        # === Дата/время ===
        analysis.datetime_original = self._get_tag_value(exif, 
            'DateTimeOriginal', 'EXIF:DateTimeOriginal', 'CreateDate'
        )
        analysis.datetime_digitized = self._get_tag_value(exif, 'DateTimeDigitized', 'EXIF:DateTimeDigitized')
        analysis.file_modify_date = self._get_tag_value(exif, 'FileModifyDate', 'File:FileModifyDate')
        
        # === ГЛАВНОЕ: Shutter Count ===
        shutter, source = self._find_shutter_count(exif)
        analysis.shutter_count = shutter
        analysis.shutter_count_source = source
        analysis.shutter_count_present = shutter is not None
        
        if not analysis.shutter_count_present:
            analysis.exif_integrity_notes.append(
                "⚠️ Shutter count в EXIF отсутствует / Shutter count in EXIF not present; "
                "cannot be determined from this file. Для Canon это частое явление."
            )
        
        # === Косвенные данные (НЕ пробег!) ===
        analysis.file_number_hint = self._extract_file_number(path.name)
        
        # FileNumber из EXIF
        exif_file_num = self._get_tag_value(exif, 'FileNumber', 'Canon:FileNumber', 'FileIndex')
        if exif_file_num and isinstance(exif_file_num, (int, float)):
            analysis.file_number_hint = int(exif_file_num)
        
        analysis.directory_number = self._get_tag_value(exif, 'DirectoryIndex', 'Canon:DirectoryIndex')
        analysis.image_unique_id = self._get_tag_value(exif, 'ImageUniqueID', 'EXIF:ImageUniqueID')
        
        # === Детектор обработки ===
        analysis.software = self._get_tag_value(exif, 'Software', 'EXIF:Software')
        analysis.processing_software = self._get_tag_value(exif, 'ProcessingSoftware', 'EXIF:ProcessingSoftware')
        
        edited, warning = self._check_editing_software(analysis.software, analysis.processing_software)
        analysis.not_out_of_camera = edited
        analysis.editing_detected_warning = warning
        
        if edited:
            analysis.exif_integrity_notes.append(warning)
        
        # === Технические параметры съёмки ===
        analysis.iso = self._get_tag_value(exif, 'ISO', 'EXIF:ISO')
        analysis.aperture = str(self._get_tag_value(exif, 'FNumber', 'Aperture', 'ApertureValue') or '')
        analysis.shutter_speed = str(self._get_tag_value(exif, 'ExposureTime', 'ShutterSpeed', 'ShutterSpeedValue') or '')
        analysis.focal_length = str(self._get_tag_value(exif, 'FocalLength', 'EXIF:FocalLength') or '')
        
        # Размеры
        analysis.image_width = self._get_tag_value(exif, 'ImageWidth', 'ExifImageWidth')
        analysis.image_height = self._get_tag_value(exif, 'ImageHeight', 'ExifImageHeight')
        
        # === Проверки целостности ===
        # Проверка на ресайз (признак обработки)
        orig_width = self._get_tag_value(exif, 'OriginalImageWidth')
        orig_height = self._get_tag_value(exif, 'OriginalImageHeight')
        if orig_width and orig_height:
            if analysis.image_width and (orig_width != analysis.image_width or orig_height != analysis.image_height):
                analysis.exif_integrity_notes.append(
                    "⚠️ Размер изображения отличается от оригинала — возможен экспорт/ресайз"
                )
        
        # Проверка XMP (признак обработки)
        xmp_creator = self._get_tag_value(exif, 'XMP:CreatorTool', 'CreatorTool')
        if xmp_creator:
            analysis.exif_integrity_notes.append(f"XMP CreatorTool: {xmp_creator}")
        
        return analysis
    
    def analyze_directory(self, dir_path: str, include_raw_exif: bool = False) -> List[FileAnalysis]:
        """Анализ всех поддерживаемых файлов в директории."""
        results = []
        path = Path(dir_path)
        
        for file_path in path.iterdir():
            if file_path.is_file() and file_path.suffix.lower() in self.SUPPORTED_EXTENSIONS:
                results.append(self.analyze_file(str(file_path), include_raw_exif))
        
        return sorted(results, key=lambda x: x.datetime_original or '')
    
    def compare_files(self, file1_path: str, file2_path: str) -> ComparisonResult:
        """
        Сравнение двух файлов для проверки "от одной ли камеры".
        
        Режим проверки продавца на Авито и т.п.
        """
        analysis1 = self.analyze_file(file1_path)
        analysis2 = self.analyze_file(file2_path)
        
        reasons = []
        verdict = VerificationResult.INCONCLUSIVE
        
        # === Проверка модели ===
        same_model = (
            analysis1.camera_make == analysis2.camera_make and
            analysis1.camera_model == analysis2.camera_model and
            analysis1.camera_make is not None
        )
        
        if same_model:
            reasons.append(f"✓ Одинаковая модель: {analysis1.camera_make} {analysis1.camera_model}")
        elif analysis1.camera_model and analysis2.camera_model:
            reasons.append(f"✗ РАЗНЫЕ модели: {analysis1.camera_model} vs {analysis2.camera_model}")
            verdict = VerificationResult.SUSPICIOUS
        
        # === Проверка серийного номера ===
        same_serial = None
        if analysis1.serial_number and analysis2.serial_number:
            same_serial = analysis1.serial_number == analysis2.serial_number
            if same_serial:
                reasons.append(f"✓ Одинаковый серийный номер: {analysis1.serial_number}")
            else:
                reasons.append(f"✗ РАЗНЫЕ серийные номера: {analysis1.serial_number} vs {analysis2.serial_number}")
                verdict = VerificationResult.SUSPICIOUS
        else:
            reasons.append("⚠ Серийный номер не найден в одном или обоих файлах")
        
        # === Проверка прошивки ===
        same_firmware = None
        if analysis1.firmware and analysis2.firmware:
            same_firmware = analysis1.firmware == analysis2.firmware
            if same_firmware:
                reasons.append(f"✓ Одинаковая прошивка: {analysis1.firmware}")
            else:
                reasons.append(f"⚠ Разные прошивки: {analysis1.firmware} vs {analysis2.firmware} (может быть обновление)")
        
        # === Проверка последовательности времени ===
        time_diff = None
        time_seq_valid = None
        if analysis1.datetime_original and analysis2.datetime_original:
            try:
                # Парсинг даты (формат EXIF: "2024:01:15 14:30:00")
                fmt = "%Y:%m:%d %H:%M:%S"
                dt1 = datetime.strptime(analysis1.datetime_original.split('.')[0].split('+')[0], fmt)
                dt2 = datetime.strptime(analysis2.datetime_original.split('.')[0].split('+')[0], fmt)
                time_diff = (dt2 - dt1).total_seconds()
                
                if time_diff >= 0:
                    reasons.append(f"✓ Корректная последовательность времени: файл 2 снят позже на {abs(time_diff):.0f} сек")
                    time_seq_valid = True
                else:
                    reasons.append(f"⚠ Обратный порядок: файл 2 снят РАНЬШЕ на {abs(time_diff):.0f} сек")
                    time_seq_valid = False
            except ValueError:
                reasons.append("⚠ Не удалось разобрать дату съёмки")
        
        # === Проверка номера файла ===
        file_seq_valid = None
        if analysis1.file_number_hint and analysis2.file_number_hint:
            if analysis2.file_number_hint > analysis1.file_number_hint:
                reasons.append(f"✓ Номер файла увеличивается: {analysis1.file_number_hint} → {analysis2.file_number_hint}")
                file_seq_valid = True
            elif analysis2.file_number_hint == analysis1.file_number_hint:
                reasons.append(f"⚠ Одинаковые номера файлов: {analysis1.file_number_hint}")
            else:
                reasons.append(f"⚠ Номер файла уменьшается: {analysis1.file_number_hint} → {analysis2.file_number_hint} (возможен сброс счётчика)")
                file_seq_valid = False
        
        # === Проверка на редактирование ===
        if analysis1.not_out_of_camera or analysis2.not_out_of_camera:
            reasons.append("⚠ Один или оба файла были обработаны — метаданные могут быть неполными")
        
        # === Итоговый вердикт ===
        if verdict != VerificationResult.SUSPICIOUS:
            if same_serial is True and same_model:
                verdict = VerificationResult.LIKELY_SAME_CAMERA
            elif same_model and time_seq_valid and file_seq_valid:
                verdict = VerificationResult.LIKELY_SAME_CAMERA
                reasons.append("Примечание: без серийного номера — вывод менее надёжен")
            else:
                verdict = VerificationResult.INCONCLUSIVE
        
        return ComparisonResult(
            file1=analysis1.file_name,
            file2=analysis2.file_name,
            verdict=verdict,
            reasons=reasons,
            same_camera_model=same_model,
            same_serial_number=same_serial,
            same_firmware=same_firmware,
            time_sequence_valid=time_seq_valid,
            file_number_sequence_valid=file_seq_valid,
            time_difference_seconds=time_diff
        )


def format_analysis_pretty(analysis: FileAnalysis) -> str:
    """Форматирование результата для человека."""
    lines = []
    lines.append("=" * 70)
    lines.append(f"📁 ФАЙЛ: {analysis.file_name}")
    lines.append(f"   Путь: {analysis.file_path}")
    lines.append(f"   Расширение: {analysis.file_type.upper()} | Размер: {analysis.file_size_bytes / 1024 / 1024:.2f} MB")
    
    # Показать реальный тип файла
    if analysis.real_file_type:
        lines.append(f"   Реальный тип: {analysis.real_file_type} ({analysis.mime_type or 'н/д'})")
    
    # Предупреждение о несоответствии
    if analysis.file_type_mismatch:
        lines.append("")
        lines.append("   🚨🚨🚨 ВНИМАНИЕ! ФАЙЛ ПОДДЕЛЬНЫЙ! 🚨🚨🚨")
        lines.append(f"   Расширение .{analysis.file_type} НЕ соответствует содержимому ({analysis.real_file_type})")
        lines.append("   Это НЕ настоящий RAW файл с камеры!")
        lines.append("")
    
    lines.append("-" * 70)
    
    # Камера
    lines.append("📷 КАМЕРА:")
    lines.append(f"   Производитель: {analysis.camera_make or 'н/д'}")
    lines.append(f"   Модель: {analysis.camera_model or 'н/д'}")
    lines.append(f"   Серийный номер: {analysis.serial_number or 'не записан в файле'}")
    lines.append(f"   Прошивка: {analysis.firmware or 'н/д'}")
    lines.append(f"   Объектив: {analysis.lens_model or 'н/д'}")
    
    lines.append("-" * 70)
    
    # ГЛАВНОЕ: Пробег
    lines.append("🔢 ПРОБЕГ ЗАТВОРА (SHUTTER COUNT):")
    if analysis.shutter_count_present:
        lines.append(f"   ✅ НАЙДЕН: {analysis.shutter_count:,} срабатываний")
        lines.append(f"   Источник: {analysis.shutter_count_source}")
    else:
        lines.append("   ❌ НЕ НАЙДЕН В ФАЙЛЕ")
        lines.append("   ")
        lines.append("   Shutter count в EXIF отсутствует — по этому файлу определить")
        lines.append("   точный пробег НЕВОЗМОЖНО.")
        lines.append("   ")
        lines.append("   Для Canon (200D, 600D, 700D и др.) это нормально — данные")
        lines.append("   о пробеге не записываются в RAW/JPG.")
        lines.append("   ")
        lines.append("   ➡️  Для определения пробега используйте:")
        lines.append("       • Подключение камеры по USB + EOSInfo/ShutterCheck")
        lines.append("       • Сервисный центр Canon")
    
    lines.append("-" * 70)
    
    # Косвенные данные
    lines.append("📊 КОСВЕННЫЕ ДАННЫЕ (⚠️ НЕ являются пробегом!):")
    if analysis.file_number_hint:
        lines.append(f"   Номер файла (FileIndex): {analysis.file_number_hint}")
        lines.append(f"   ⚠️ {analysis.file_number_warning}")
    else:
        lines.append("   Номер файла: не определён")
    
    if analysis.directory_number:
        lines.append(f"   Номер папки: {analysis.directory_number}")
    if analysis.image_unique_id:
        lines.append(f"   ImageUniqueID: {analysis.image_unique_id}")
    
    lines.append("-" * 70)
    
    # Дата съёмки
    lines.append("📅 ДАТА СЪЁМКИ:")
    lines.append(f"   Оригинал: {analysis.datetime_original or 'н/д'}")
    lines.append(f"   Модификация файла: {analysis.file_modify_date or 'н/д'}")
    
    # Параметры съёмки
    lines.append("-" * 70)
    lines.append("⚙️ ПАРАМЕТРЫ СЪЁМКИ:")
    lines.append(f"   ISO: {analysis.iso or 'н/д'}")
    lines.append(f"   Диафрагма: f/{analysis.aperture}" if analysis.aperture else "   Диафрагма: н/д")
    lines.append(f"   Выдержка: {analysis.shutter_speed}" if analysis.shutter_speed else "   Выдержка: н/д")
    lines.append(f"   Фокусное: {analysis.focal_length}" if analysis.focal_length else "   Фокусное: н/д")
    lines.append(f"   Размер: {analysis.image_width}x{analysis.image_height}" if analysis.image_width else "   Размер: н/д")
    
    # Предупреждения
    if analysis.not_out_of_camera or analysis.exif_integrity_notes:
        lines.append("-" * 70)
        lines.append("⚠️ ПРЕДУПРЕЖДЕНИЯ:")
        if analysis.not_out_of_camera:
            lines.append(f"   🔴 {analysis.editing_detected_warning}")
        for note in analysis.exif_integrity_notes:
            if note != analysis.editing_detected_warning:
                lines.append(f"   • {note}")
    
    # Ошибки
    if analysis.errors:
        lines.append("-" * 70)
        lines.append("❌ ОШИБКИ:")
        for err in analysis.errors:
            lines.append(f"   {err}")
    
    lines.append("=" * 70)
    return "\n".join(lines)


def format_comparison_pretty(result: ComparisonResult) -> str:
    """Форматирование результата сравнения."""
    lines = []
    lines.append("=" * 70)
    lines.append("🔍 СРАВНЕНИЕ ДВУХ ФАЙЛОВ (режим проверки продавца)")
    lines.append("=" * 70)
    lines.append(f"📁 Файл 1: {result.file1}")
    lines.append(f"📁 Файл 2: {result.file2}")
    lines.append("-" * 70)
    
    # Вердикт
    verdict_emoji = {
        VerificationResult.LIKELY_SAME_CAMERA: "✅",
        VerificationResult.INCONCLUSIVE: "❓",
        VerificationResult.SUSPICIOUS: "🚨"
    }
    verdict_text = {
        VerificationResult.LIKELY_SAME_CAMERA: "ВЕРОЯТНО ОДНА КАМЕРА",
        VerificationResult.INCONCLUSIVE: "НЕДОСТАТОЧНО ДАННЫХ",
        VerificationResult.SUSPICIOUS: "ПОДОЗРИТЕЛЬНО / РАЗНЫЕ КАМЕРЫ"
    }
    
    lines.append(f"\n{verdict_emoji[result.verdict]} ВЕРДИКТ: {verdict_text[result.verdict]}\n")
    
    lines.append("-" * 70)
    lines.append("📋 ДЕТАЛИ ПРОВЕРКИ:")
    for reason in result.reasons:
        lines.append(f"   {reason}")
    
    lines.append("=" * 70)
    return "\n".join(lines)


def analysis_to_dict(analysis: FileAnalysis) -> Dict:
    """Конвертация анализа в словарь для JSON/CSV."""
    data = asdict(analysis)
    # Убираем raw_exif для компактности (если нужен, добавить флаг)
    if 'raw_exif' in data:
        del data['raw_exif']
    return data


def save_json(analyses: List[FileAnalysis], output_path: str) -> None:
    """Сохранение в JSON."""
    data = [analysis_to_dict(a) for a in analyses]
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"✅ Сохранено в {output_path}")


def save_csv(analyses: List[FileAnalysis], output_path: str) -> None:
    """Сохранение в CSV."""
    if not analyses:
        print("Нет данных для сохранения")
        return
    
    # Основные колонки
    columns = [
        'file_name', 'file_type', 'camera_make', 'camera_model',
        'serial_number', 'firmware', 'lens_model',
        'datetime_original', 'shutter_count', 'shutter_count_present',
        'shutter_count_source', 'file_number_hint', 'not_out_of_camera',
        'iso', 'aperture', 'shutter_speed'
    ]
    
    with open(output_path, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        for analysis in analyses:
            writer.writerow(analysis_to_dict(analysis))
    
    print(f"✅ Сохранено в {output_path}")


def main():
    """Главная CLI-функция."""
    parser = argparse.ArgumentParser(
        description="""
PhotoShutterInspector — Честный анализатор EXIF для проверки пробега камеры.

⚠️ ВАЖНО: Для многих камер Canon shutter count НЕ записывается в файлы!
   В таких случаях по фото/RAW определить пробег НЕВОЗМОЖНО.
        """,
        formatter_class=argparse.RawTextHelpFormatter
    )
    
    parser.add_argument(
        'path',
        help='Путь к файлу или папке для анализа'
    )
    parser.add_argument(
        '--json', dest='json_output',
        help='Сохранить результат в JSON файл'
    )
    parser.add_argument(
        '--csv', dest='csv_output',
        help='Сохранить результат в CSV файл'
    )
    parser.add_argument(
        '--pretty', action='store_true',
        help='Человекочитаемый вывод в консоль'
    )
    parser.add_argument(
        '--raw-exif', action='store_true',
        help='Включить сырые данные ExifTool в JSON'
    )
    parser.add_argument(
        '--compare', dest='compare_file',
        help='Сравнить с другим файлом (режим проверки продавца)'
    )
    parser.add_argument(
        '--exiftool', default='exiftool',
        help='Путь к ExifTool (по умолчанию: exiftool в PATH)'
    )
    
    args = parser.parse_args()
    
    # Инициализация
    try:
        inspector = PhotoShutterInspector(exiftool_path=args.exiftool)
        print(f"ExifTool версия: {inspector.exiftool_version}")
    except RuntimeError as e:
        print(f"❌ ОШИБКА: {e}")
        sys.exit(1)
    
    path = Path(args.path)
    
    # Режим сравнения
    if args.compare_file:
        if not path.is_file():
            print(f"❌ Для сравнения нужен файл, не директория: {path}")
            sys.exit(1)
        
        result = inspector.compare_files(str(path), args.compare_file)
        print(format_comparison_pretty(result))
        
        if args.json_output:
            with open(args.json_output, 'w', encoding='utf-8') as f:
                json.dump(asdict(result), f, ensure_ascii=False, indent=2, default=str)
        sys.exit(0)
    
    # Обычный анализ
    analyses = []
    
    if path.is_file():
        analyses = [inspector.analyze_file(str(path), include_raw_exif=args.raw_exif)]
    elif path.is_dir():
        analyses = inspector.analyze_directory(str(path), include_raw_exif=args.raw_exif)
    else:
        print(f"❌ Путь не найден: {path}")
        sys.exit(1)
    
    if not analyses:
        print("Подходящих файлов не найдено")
        sys.exit(0)
    
    # Вывод
    if args.pretty or (not args.json_output and not args.csv_output):
        for analysis in analyses:
            print(format_analysis_pretty(analysis))
            print()
    
    if args.json_output:
        save_json(analyses, args.json_output)
    
    if args.csv_output:
        save_csv(analyses, args.csv_output)
    
    # Итоговая статистика
    with_shutter = sum(1 for a in analyses if a.shutter_count_present)
    edited = sum(1 for a in analyses if a.not_out_of_camera)
    
    print("-" * 70)
    print(f"📊 ИТОГО: {len(analyses)} файлов")
    print(f"   ✅ С пробегом затвора: {with_shutter}")
    print(f"   ❌ Без пробега (невозможно определить по файлу): {len(analyses) - with_shutter}")
    print(f"   ⚠️  Обработанных/экспортированных: {edited}")


if __name__ == '__main__':
    main()
