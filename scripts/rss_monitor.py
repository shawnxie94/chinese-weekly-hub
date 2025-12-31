#!/usr/bin/env python3
"""
RSS 停更巡检脚本
每月定时检查RSS源的更新状态，对超过1个月未更新的源添加停更标记并移至列表末尾
"""

import re
import os
import sys
import feedparser
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
import requests
import warnings

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

README_PATH = os.environ.get('README_PATH', 'README.md')

def is_separator_row(cells):
    """检查是否是分隔符行"""
    if len(cells) != 5:
        return False
    return all(cell.strip() in ['---', ''] or cell.strip().startswith(':') or cell.strip().endswith(':') for cell in cells)

def is_empty_row(cells):
    """检查是否是空行"""
    if len(cells) != 5:
        return False
    return all(cell.strip() == '' for cell in cells)

def parse_readme_table(readme_content):
    """解析README.md中的RSS表格"""
    pattern = r'\|[^|\n]+\|[^|\n]+\|[^|\n]+\|[^|\n]+\|[^|\n]+\|'
    matches = re.findall(pattern, readme_content)

    headers = ['名称', '简介', '付费？', '链接', 'RSS']
    entries = []

    for match in matches[1:]:
        cells = [cell.strip() for cell in match.strip('|').split('|')]
        if len(cells) == 5 and not is_separator_row(cells) and not is_empty_row(cells):
            entry = dict(zip(headers, cells))
            rss_url = entry['RSS']
            link_url = entry['链接']
            rss_match = re.search(r'\[rss\]\((.*?)\)', rss_url)
            link_match = re.search(r'\[link\]\((.*?)\)', link_url)
            if rss_match:
                entry['RSS'] = rss_match.group(1)
            if link_match:
                entry['链接'] = link_match.group(1)
            entries.append(entry)

    return entries

def get_rss_last_updated(rss_url, timeout=10):
    """获取RSS源的最近更新时间"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(rss_url, headers=headers, timeout=timeout)
        response.raise_for_status()

        feed = feedparser.parse(response.content)

        if feed.entries:
            latest_entry = feed.entries[0]
            if hasattr(latest_entry, 'published_parsed') and latest_entry.published_parsed:
                return datetime(*latest_entry.published_parsed[:6])
            elif hasattr(latest_entry, 'updated_parsed') and latest_entry.updated_parsed:
                return datetime(*latest_entry.updated_parsed[:6])
            elif hasattr(latest_entry, 'updated'):
                try:
                    return datetime.strptime(latest_entry.updated[:19], '%Y-%m-%dT%H:%M:%S')
                except:
                    pass

            soup = BeautifulSoup(response.content, 'html.parser')
            for date_attr in ['pubdate', 'dc:date', 'updated']:
                date_elem = soup.find(attrs={'name': date_attr}) or soup.find(attrs={'property': date_attr})
                if date_elem and date_elem.get('content'):
                    try:
                        return datetime.fromisoformat(date_elem['content'].replace('Z', '+00:00'))
                    except:
                        continue

        return None
    except Exception as e:
        print(f"  警告: 无法获取 {rss_url}: {e}")
        return None

def calculate_months_since_update(last_updated):
    """计算距离上次更新经过的月数"""
    if not last_updated:
        return None

    now = datetime.now(last_updated.tzinfo) if last_updated.tzinfo else datetime.now()
    diff = relativedelta(now, last_updated)
    return diff.years * 12 + diff.months

def extract_stopped_months(name):
    """从名称中提取已有的停更月数"""
    pattern = r'【停更(\d+)月】'
    match = re.search(pattern, name)
    if match:
        return int(match.group(1))
    return None

def update_entry_name(name, months):
    """更新条目名称，添加或修改停更标记"""
    clean_name = re.sub(r'【停更\d+月】', '', name).strip()
    clean_name = re.sub(r'【停更】', '', clean_name).strip()
    if months is not None and months >= 1:
        return f"【停更{months}月】{clean_name}"
    return clean_name

def clean_stopped_marker(name):
    """清理已有的停更标记"""
    clean_name = re.sub(r'【停更\d+月】', '', name).strip()
    clean_name = re.sub(r'【停更】', '', clean_name).strip()
    return clean_name

def is_legacy_stopped(name):
    """检查是否是旧的【停更】标记（没有月数）"""
    return '【停更】' in name and not re.search(r'【停更\d+月】', name)

def process_entries(entries):
    """处理所有条目，检查更新状态"""
    results = []

    for entry in entries:
        name = entry['名称']
        rss_url = entry['RSS']

        print(f"检查: {name}")

        last_updated = get_rss_last_updated(rss_url)
        months_since_update = calculate_months_since_update(last_updated)

        if months_since_update is None:
            print(f"  状态: 无法获取更新时间")
            entry['last_updated'] = None
            entry['months'] = None
        else:
            print(f"  最近更新: {last_updated.strftime('%Y-%m-%d')}, 距今: {months_since_update} 个月")
            entry['last_updated'] = last_updated
            entry['months'] = months_since_update

        results.append(entry)

    return results

def sort_and_mark_entries(entries):
    """排序并标记停更条目"""
    active_entries = []
    stopped_entries = []

    for entry in entries:
        name = entry['名称']
        months = entry.get('months')

        clean_name = clean_stopped_marker(name)

        if months is not None and months >= 1:
            updated_name = update_entry_name(clean_name, months)
            entry['名称'] = updated_name
            stopped_entries.append(entry)
        elif months is None:
            updated_name = f"【停更】{clean_name}"
            entry['名称'] = updated_name
            entry['months'] = 0
            stopped_entries.append(entry)
        else:
            if '【停更' not in clean_name:
                entry['名称'] = clean_name
                active_entries.append(entry)
            else:
                entry['名称'] = clean_name
                active_entries.append(entry)

    stopped_entries.sort(key=lambda x: x.get('months', 0), reverse=True)

    return active_entries + stopped_entries

def generate_table(entries):
    """生成Markdown表格"""
    header = "| 名称 | 简介 | 付费？ | 链接 | RSS |\n"
    separator = "| --- | --- | --- | --- | --- |\n"

    rows = []
    for entry in entries:
        name = entry['名称']
        intro = entry['简介']
        paid = entry['付费？']
        link = entry['链接']
        rss = entry['RSS']

        row = f"| {name} | {intro} | {paid} | [link]({link}) | [rss]({rss}) |\n"
        rows.append(row)

    return header + separator + ''.join(rows)

def update_readme(readme_path, new_table):
    """更新README.md文件"""
    with open(readme_path, 'r', encoding='utf-8') as f:
        content = f.read()

    start_marker = "## 列表"
    end_marker = "## 贡献"

    start_idx = content.find(start_marker)
    end_idx = content.find(end_marker)

    if start_idx == -1 or end_idx == -1:
        print("错误: 找不到列表的起始或结束标记")
        return False

    new_content = content[:start_idx] + start_marker + "\n" + new_table + "\n" + content[end_idx:]

    with open(readme_path, 'w', encoding='utf-8') as f:
        f.write(new_content)

    return True

def update_status_section(readme_path, active_count, stopped_count, changes=None):
    """更新README.md中的状态部分"""
    with open(readme_path, 'r', encoding='utf-8') as f:
        content = f.read()

    status_marker = "## 状态"
    list_marker = "## 列表"

    status_idx = content.find(status_marker)
    list_idx = content.find(list_marker)

    if status_idx == -1 or list_idx == -1:
        return False

    if changes:
        change_desc = f"（较上月{changes}）"
    else:
        change_desc = ""

    new_status = f"""## 状态
- 活跃源: {active_count}{change_desc}
- 停更源: {stopped_count}{change_desc}

"""

    new_content = content[:status_idx] + new_status + content[list_idx:]

    with open(readme_path, 'w', encoding='utf-8') as f:
        f.write(new_content)

    return True


def main():
    print(f"开始RSS停更巡检... {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    with open(README_PATH, 'r', encoding='utf-8') as f:
        readme_content = f.read()

    entries = parse_readme_table(readme_content)
    print(f"共找到 {len(entries)} 个RSS源\n")

    stopped_count_old = sum(1 for e in entries if '【停更' in e['名称'])

    processed_entries = process_entries(entries)
    sorted_entries = sort_and_mark_entries(processed_entries)

    new_table = generate_table(sorted_entries)

    updated = update_readme(README_PATH, new_table)

    if updated:
        print("\n" + "=" * 60)
        print("README.md 已更新")

        stopped_count = sum(1 for e in sorted_entries if '【停更' in e['名称'])
        active_count = len(sorted_entries) - stopped_count

        stopped_change = stopped_count - stopped_count_old
        active_change = active_count - (len(entries) - stopped_count_old)

        changes = []
        if active_change != 0:
            sign = "+" if active_change > 0 else ""
            changes.append(f"{sign}{active_change}个活跃")
        if stopped_change != 0:
            sign = "+" if stopped_change > 0 else ""
            changes.append(f"{sign}{stopped_change}个停更")

        change_desc = "，".join(changes) if changes else None

        update_status_section(README_PATH, active_count, stopped_count, change_desc)

        print(f"活跃源: {active_count}, 停更源: {stopped_count}")

        with open(README_PATH, 'r', encoding='utf-8') as f:
            new_content = f.read()

        if new_content != readme_content:
            print("文件内容有变化，将提交更改")
            with open('.rss_updated', 'w') as f:
                f.write('true')
        else:
            print("文件内容无变化")
    else:
        print("更新失败")
        sys.exit(1)

if __name__ == '__main__':
    main()
