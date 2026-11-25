"""
Script gom nhóm và sắp xếp các file font thành từng thư mục font family.
- Các font có nhiều biến thể (Bold, Italic, Regular...) được gom vào thư mục chung của family.
- Các font chỉ có 1 file lẻ cũng được đặt vào thư mục riêng mang tên font đó.
- Hỗ trợ chế độ --dry-run (chỉ xem trước) và --execute (thực thi di chuyển).
"""

import argparse
import os
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path

# Danh sách từ khóa phong cách font phổ biến
COMPOUND_STYLES = [
    'semibolditalic', 'demibolditalic', 'extrabolditalic', 'ultrabolditalic',
    'bolditalic', 'boldoblique', 'romanoblique', 'lightitalic', 'thinitalic',
    'mediumitalic', 'blackitalic', 'heavyitalic', 'bookitalic',
    'italiccyrillic', 'boldcyrillic', 'italiccyr', 'boldcyr',
    'smbdsubhead', 'smbdcaption', 'smbddisplay',
    'subhead', 'caption', 'display', 'poster',
    'regular', 'bold', 'italic', 'oblique', 'roman', 'book',
    'light', 'thin', 'hairline', 'extralight', 'ultralight',
    'medium', 'demi', 'demibold', 'semibold', 'black', 'heavy',
    'extra', 'extrabold', 'ultrabold', 'condensed', 'cond', 'narrow',
    'extended', 'wide',
    'normal', 'slanted', 'upright', 'outline', 'shadow', 'unicode', 'uni',
    'smbd', 'bd', 'it', 'reg'
]

DELIMITED_STYLE_REGEX = re.compile(
    r'[\s\-_]+(' + '|'.join(COMPOUND_STYLES) + r')([\s\-_]+.*)?$',
    re.IGNORECASE
)

# Nhận diện quy ước Type1 8 ký tự với dấu gạch dưới (ví dụ: Aliee__.ttf, Alieeb_.ttf, AOBT____.SHX)
TYPE1_UNDERSCORE_REGEX = re.compile(r'^([a-zA-Z0-9]{2,})_[a-zA-Z0-9_]{1,5}$')

# Nhận diện hậu tố ngắn CAD/VNI (ví dụ: B, I, BI, N, R, BD, IT...)
SHORT_SUFFIX_REGEX = re.compile(
    r'^(.*?)(bi|bd|it|bo|b|i|n|r|o|s|c|d|t|h)$',
    re.IGNORECASE
)

# Nhận diện biến thể 1 ký tự cuối (ví dụ: 1-ARAB1A, 1-ARAB1B)
SINGLE_LETTER_VARIANT_REGEX = re.compile(r'^(.*?)[_-]?([a-zA-Z])$')

# Các ký tự không hợp lệ trong tên thư mục Windows
INVALID_FOLDER_CHARS = re.compile(r'[<>:"/\\|?*]')


def sanitize_folder_name(name: str) -> str:
    """Loại bỏ ký tự cấm và khoảng trắng thừa cho tên thư mục Windows."""
    clean = INVALID_FOLDER_CHARS.sub('_', name).strip('. ')
    return clean if clean else "Unknown_Font"


def get_candidate_stems(stem: str) -> list[str]:
    """Tạo danh sách các ứng viên tên gốc (candidate base names) cho file."""
    cands = [stem]

    # 1. Tách style có phân tách (dấu gạch ngang, khoảng trắng, gạch dưới)
    m1 = DELIMITED_STYLE_REGEX.search(stem)
    if m1:
        base = stem[:m1.start()].strip(' -_')
        if base and len(base) >= 2:
            cands.append(base)

    # 2. Định dạng Type1 gạch dưới
    m2 = TYPE1_UNDERSCORE_REGEX.match(stem)
    if m2:
        base = m2.group(1).rstrip('_')
        if len(base) >= 2:
            cands.append(base)

    # 3. Hậu tố ngắn (CAD/VNI short style suffix)
    m3 = SHORT_SUFFIX_REGEX.match(stem)
    if m3 and len(m3.group(1)) >= 3:
        cands.append(m3.group(1))

    # 4. Biến thể ký tự đơn cuối (A, B, C...)
    m4 = SINGLE_LETTER_VARIANT_REGEX.match(stem)
    if m4 and len(m4.group(1)) >= 3:
        cands.append(m4.group(1))

    # 5. Loại bỏ chữ số cuối nếu cùng nhóm (ví dụ: ALLBN, ALLBN1, ALLBN2)
    no_digits = re.sub(r'[0-9]+$', '', stem).rstrip(' -_')
    if len(no_digits) >= 3 and no_digits != stem:
        cands.append(no_digits)

    return cands


def group_fonts_in_directory(dir_path: Path) -> dict[str, list[str]]:
    """Phân tích các file font trực tiếp trong dir_path và gom nhóm."""
    font_extensions = {'.ttf', '.otf', '.shx', '.fon', '.ttc', '.pfb', '.pfm'}
    
    # Chỉ lấy các file ở cấp gốc của dir_path (bỏ qua các thư mục con)
    files = [
        f.name for f in dir_path.iterdir()
        if f.is_file() and f.suffix.lower() in font_extensions
    ]

    if not files:
        return {}

    # Bước 1: Trích xuất các candidate cho từng file
    file_candidates: dict[str, list[str]] = {}
    candidate_counts: dict[str, set[str]] = defaultdict(set)

    for fname in files:
        stem = Path(fname).stem
        cands = get_candidate_stems(stem)
        file_candidates[fname] = cands
        for c in cands:
            candidate_counts[c.upper()].add(fname)

    # Bước 2: Chọn candidate tốt nhất cho mỗi file
    file_to_group: dict[str, str] = {}
    display_names: dict[str, str] = {}

    for fname, cands in file_candidates.items():
        # Lọc các candidate có từ 2 file trở lên cùng chia sẻ
        multi_cands = [c for c in cands if len(candidate_counts[c.upper()]) > 1]
        if multi_cands:
            # Ưu tiên candidate có nhiều file nhất, nếu bằng nhau thì ưu tiên tên dài hơn
            best = max(multi_cands, key=lambda c: (len(candidate_counts[c.upper()]), len(c)))
        else:
            # File đơn lẻ (không có họ hàng): giữ nguyên stem gốc
            best = cands[0]

        group_key = best.upper()
        file_to_group[fname] = group_key

        # Lưu tên hiển thị đẹp (giữ chữ hoa/thường nguyên bản)
        if group_key not in display_names or (len(best) > len(display_names[group_key]) and not best.isupper()):
            display_names[group_key] = best

    # Bước 3: Tập hợp kết quả gom nhóm
    groups: dict[str, list[str]] = defaultdict(list)
    for fname, g_key in file_to_group.items():
        folder_name = sanitize_folder_name(display_names[g_key])
        groups[folder_name].append(fname)

    return dict(groups)


def organize_directory(dir_path: Path, execute: bool = False) -> None:
    """Gom nhóm font trong 1 thư mục cụ thể."""
    print(f"\n=======================================================")
    print(f" Đang quét thư mục: {dir_path}")
    print(f"=======================================================")

    if not dir_path.exists():
        print(f"Lỗi: Thư mục không tồn tại: {dir_path}")
        return

    groups = group_fonts_in_directory(dir_path)
    total_files = sum(len(v) for v in groups.values())

    if total_files == 0:
        print("Không tìm thấy file font nào cần sắp xếp ở cấp gốc.")
        return

    multi_groups = {k: v for k, v in groups.items() if len(v) > 1}
    single_groups = {k: v for k, v in groups.items() if len(v) == 1}

    print(f"Tổng số file font: {total_files}")
    print(f"Số nhóm font có nhiều biến thể: {len(multi_groups)} nhóm ({sum(len(v) for v in multi_groups.values())} files)")
    print(f"Số font lẻ (mỗi font 1 thư mục riêng): {len(single_groups)} nhóm ({len(single_groups)} files)")
    print(f"Tổng số thư mục sẽ tạo: {len(groups)}")

    # In mẫu một số nhóm đa biến thể
    print("\n--- Mẫu một số nhóm font gia đình (multi-variant): ---")
    for k in list(multi_groups.keys())[:10]:
        print(f"  Folder: [{k}/] ({len(multi_groups[k])} files) -> {multi_groups[k]}")

    # In mẫu một số nhóm font đơn lẻ
    print("\n--- Mẫu một số font đơn lẻ (single font): ---")
    for k in list(single_groups.keys())[:5]:
        print(f"  Folder: [{k}/] -> {single_groups[k][0]}")

    if not execute:
        print(f"\n[DRY-RUN]: Đây là chế độ chạy thử, chưa có file nào bị di chuyển.")
        print(f"Để thực thi thật, chạy lệnh với cờ: --execute")
        return

    # Thực thi di chuyển
    print(f"\n[EXECUTE]: Bắt đầu di chuyển {total_files} file...")
    moved_count = 0
    error_count = 0

    for folder_name, fnames in groups.items():
        target_dir = dir_path / folder_name
        target_dir.mkdir(parents=True, exist_ok=True)

        for fname in fnames:
            src = dir_path / fname
            dst = target_dir / fname

            if not src.exists():
                continue

            try:
                # Nếu dst đã tồn tại (trùng tên file)
                if dst.exists() and dst != src:
                    stem = dst.stem
                    suffix = dst.suffix
                    dst = target_dir / f"{stem}_duplicate{suffix}"
                
                shutil.move(str(src), str(dst))
                moved_count += 1
            except Exception as e:
                print(f"Lỗi khi di chuyển {fname}: {e}")
                error_count += 1

    print(f"Hoàn thành! Đã di chuyển: {moved_count} file. Lỗi: {error_count} file.")

    # Tự động cập nhật catalog.json sau khi di chuyển
    generate_catalog(dir_path)


def format_size(size_bytes: int) -> str:
    """Định dạng dung lượng file thành chuỗi dễ đọc (B, KB, MB)."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.2f} MB"


def generate_catalog(dir_path: Path) -> Path:
    """Tạo file catalog.json lưu danh mục font tại thư mục gốc dir_path."""
    import json
    from datetime import datetime, timezone

    font_extensions = {'.ttf', '.otf', '.shx', '.fon', '.ttc', '.pfb', '.pfm'}
    catalog_file = dir_path / "catalog.json"

    # Lấy danh sách các thư mục con (mỗi thư mục con đại diện cho 1 họ/tên font)
    subdirs = sorted([d for d in dir_path.iterdir() if d.is_dir()], key=lambda d: d.name.lower())

    families = []
    total_files = 0
    total_size_bytes = 0

    for d in subdirs:
        # Lấy danh sách các file font trong thư mục con này
        files_in_dir = sorted(
            [f for f in d.iterdir() if f.is_file() and f.suffix.lower() in font_extensions],
            key=lambda f: f.name.lower()
        )
        if not files_in_dir:
            continue

        file_items = []
        for f in files_in_dir:
            size = f.stat().st_size
            total_files += 1
            total_size_bytes += size
            # Dùng forward slash / để chuẩn hóa đa nền tảng
            rel_path = f"{d.name}/{f.name}"
            file_items.append({
                "name": f.name,
                "path": rel_path,
                "extension": f.suffix.lower(),
                "size_bytes": size,
                "size_formatted": format_size(size)
            })

        families.append({
            "name": d.name,
            "count": len(file_items),
            "files": file_items
        })

    catalog_data = {
        "folder": dir_path.name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_families": len(families),
        "total_files": total_files,
        "total_size_bytes": total_size_bytes,
        "total_size_formatted": format_size(total_size_bytes),
        "families": families
    }

    with open(catalog_file, "w", encoding="utf-8") as out:
        json.dump(catalog_data, out, ensure_ascii=False, indent=2)

    print(f"Đã tạo file catalog: {catalog_file}")
    print(f"  - Tổng số font families: {len(families)}")
    print(f"  - Tổng số file font: {total_files} ({format_size(total_size_bytes)})")
    return catalog_file


def undo_directory(dir_path: Path) -> None:
    """Hoàn tác: chuyển toàn bộ file từ các thư mục con cấp 1 về lại thư mục gốc dir_path."""
    print(f"\n=======================================================")
    print(f" [UNDO] Đang hoàn tác tại: {dir_path}")
    print(f"=======================================================")

    subdirs = [d for d in dir_path.iterdir() if d.is_dir()]
    restored = 0

    for d in subdirs:
        for f in list(d.iterdir()):
            if f.is_file():
                dest = dir_path / f.name
                shutil.move(str(f), str(dest))
                restored += 1
        try:
            d.rmdir()
        except OSError:
            pass

    print(f"Đã hoàn tác: di chuyển {restored} file về lại thư mục gốc {dir_path.name}/.")


def main():
    parser = argparse.ArgumentParser(
        description="Script gom nhóm các file font vào các thư mục tương ứng."
    )
    parser.add_argument(
        '--targets',
        nargs='+',
        default=['TTF-Fonts', 'SHX-fonts'],
        help="Danh sách thư mục cần xử lý (mặc định: TTF-Fonts SHX-fonts)"
    )
    parser.add_argument(
        '--execute',
        action='store_true',
        help="Thực hiện di chuyển file thật sự. Mặc định là chạy thử (--dry-run)."
    )
    parser.add_argument(
        '--undo',
        action='store_true',
        help="Hoàn tác: chuyển toàn bộ file từ các thư mục con về lại thư mục gốc."
    )
    parser.add_argument(
        '--catalog',
        action='store_true',
        help="Chỉ tạo/cập nhật file catalog.json cho các thư mục mục tiêu mà không di chuyển file."
    )

    args = parser.parse_args()

    root_dir = Path(__file__).resolve().parent

    for target in args.targets:
        target_path = Path(target)
        if not target_path.is_absolute():
            target_path = root_dir / target_path
        if args.undo:
            undo_directory(target_path)
        elif args.catalog:
            generate_catalog(target_path)
        else:
            organize_directory(target_path, execute=args.execute)


if __name__ == '__main__':
    main()
