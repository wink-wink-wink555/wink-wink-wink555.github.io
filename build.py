#!/usr/bin/env python3
"""Render an academic homepage from reviewed public data; Python 3.9+, no packages."""
import argparse
import hashlib
import html
import json
from pathlib import Path
import re
import shutil
from string import Template
from urllib.parse import urlsplit, unquote

LABELS = {
    'en': {'about': 'About Me', 'publications': 'Publications', 'projects': 'Projects',
           'experience': 'Internships', 'education': 'Education', 'awards': 'Awards',
           'skills': 'Skills', 'service': 'Service & Teaching', 'menu': 'Menu'},
    'zh': {'about': '关于我', 'publications': '论文发表', 'projects': '项目经历',
           'experience': '研究与工作经历', 'education': '教育背景', 'awards': '荣誉奖励',
           'skills': '技能', 'service': '教学与服务', 'menu': '菜单'},
}
STRINGS = {'name', 'position', 'affiliation', 'degree', 'email', 'description',
           'site_url', 'avatar', 'cv', 'language', 'publication_note', 'theme', 'background'}
CATALOG = json.loads((Path(__file__).resolve().parent / 'designs.json').read_text(encoding='utf-8'))
THEMES = {item['id']: item for item in CATALOG['themes']}
BACKGROUNDS = {'none'} | {item['id'] for item in CATALOG['effects']}
LISTS = {'about', 'links', 'additional_emails', 'publications', 'projects', 'experience', 'education',
         'awards', 'skills', 'service', 'section_order'}
ENTRY_KEYS = {'title', 'organization', 'dates', 'details', 'detail_links', 'url', 'links', 'group'}
PUB_KEYS = {'title', 'authors', 'venue', 'year', 'badge', 'notes', 'image', 'links'}
ORDER = ['about', 'publications', 'projects', 'experience', 'education', 'awards', 'skills', 'service']
EMAIL_PATTERN = re.compile(r'[^\s@<>?&#]+@[^\s@<>?&#]+\.[^\s@<>?&#]+')


def esc(value):
    return html.escape(str(value), quote=True)


def safe_url(value, local=False):
    if not isinstance(value, str) or not value or any(c.isspace() or ord(c) < 32 for c in value):
        raise ValueError('Links must be nonempty URLs without whitespace.')
    parts = urlsplit(value)
    if parts.scheme in ('https', 'http') and parts.netloc and not parts.username and not parts.password:
        return value
    decoded = unquote(value)
    if local and not parts.scheme and not parts.netloc and not parts.query and not parts.fragment:
        if decoded.startswith('assets/') and '\\' not in decoded and not any(p in ('..', '.', '') for p in decoded.split('/')):
            return value
    raise ValueError('Use an http(s) URL or, for media, a file under assets/: ' + value)


def local_media(value):
    safe_url(value, local=True)
    if urlsplit(value).scheme:
        raise ValueError('Media must be a local file under assets/: ' + value)
    return unquote(value)


def validate_links(links):
    if not isinstance(links, list):
        raise ValueError('links must be an array.')
    for link in links:
        if not isinstance(link, dict) or set(link) != {'label', 'url'} or not isinstance(link['label'], str) or not link['label'].strip():
            raise ValueError('Each link needs exactly label and url.')
        safe_url(link['url'])


def validate(data, root=None):
    if not isinstance(data, dict):
        raise ValueError('Profile must be a JSON object.')
    unknown = set(data) - STRINGS - LISTS
    if unknown:
        raise ValueError('Unknown profile fields (possibly private CV data): ' + ', '.join(sorted(unknown)))
    if not isinstance(data.get('name'), str) or not data['name'].strip():
        raise ValueError('name is required.')
    for key in STRINGS & data.keys():
        if not isinstance(data[key], str):
            raise ValueError(key + ' must be text.')
    for key in LISTS & data.keys():
        if not isinstance(data[key], list):
            raise ValueError(key + ' must be an array.')
    if data.get('language', 'en') not in LABELS:
        raise ValueError('language must be en or zh.')
    if data.get('theme', 'classic') not in THEMES:
        raise ValueError('Unknown theme. Choose one of: ' + ', '.join(THEMES))
    if data.get('background', 'none') not in BACKGROUNDS:
        raise ValueError('Unknown background. Choose one of: ' + ', '.join(sorted(BACKGROUNDS)))
    email = data.get('email', '')
    if email and not EMAIL_PATTERN.fullmatch(email):
        raise ValueError('email must be a plain email address.')
    if any(not isinstance(value, str) or not EMAIL_PATTERN.fullmatch(value)
           for value in data.get('additional_emails', [])):
        raise ValueError('additional_emails must contain plain email addresses.')
    if data.get('site_url'):
        safe_url(data['site_url'])
    validate_links(data.get('links', []))
    order = data.get('section_order', ORDER)
    if any(k not in ORDER for k in order) or len(order) != len(set(order)):
        raise ValueError('section_order must contain unique known section names.')
    missing = [k for k in ORDER if data.get(k) and k not in order]
    if missing:
        raise ValueError('section_order would hide populated sections: ' + ', '.join(missing))
    for key in ['about', 'awards', 'skills']:
        if any(not isinstance(x, str) for x in data.get(key, [])):
            raise ValueError(key + ' must contain only text.')
    for key in ['projects', 'experience', 'education', 'service', 'publications']:
        for item in data.get(key, []):
            keys = PUB_KEYS if key == 'publications' else ENTRY_KEYS
            if not isinstance(item, dict) or set(item) - keys or not isinstance(item.get('title'), str) or not item['title'].strip():
                raise ValueError(key + ': each entry needs a title and only documented fields.')
            for field, value in item.items():
                if field == 'links':
                    validate_links(value)
                elif field == 'detail_links':
                    if not isinstance(value, list):
                        raise ValueError('detail_links must be an array.')
                    seen = set()
                    for detail_link in value:
                        if (not isinstance(detail_link, dict) or set(detail_link) != {'text', 'url'}
                                or not isinstance(detail_link['text'], str) or not detail_link['text'].strip()):
                            raise ValueError('Each detail link needs exactly text and url.')
                        if detail_link['text'] in seen:
                            raise ValueError('detail link text must be unique within an entry.')
                        seen.add(detail_link['text'])
                        safe_url(detail_link['url'])
                elif field == 'details':
                    if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
                        raise ValueError('details must be a list of text.')
                elif not isinstance(value, str):
                    raise ValueError(field + ' must be text.')
            if item.get('url'):
                safe_url(item['url'])
    media = [data.get('avatar'), data.get('cv')] + [p.get('image') for p in data.get('publications', [])]
    for path in filter(None, media):
        relative = local_media(path)
        if root:
            target = (root / relative).resolve()
            assets_root = (root / 'assets').resolve()
            if assets_root not in target.parents or not target.is_file():
                raise ValueError('Missing or unsafe media file: ' + path)
    return data


def link(label, url, css=''):
    return '<a class="{}" href="{}">{}</a>'.format(css, esc(url), esc(label))


GITHUB_ICON = ('<svg class="brand-icon github-icon" width="14" height="14" viewBox="0 0 16 16" aria-hidden="true" focusable="false">'
               '<path fill="currentColor" d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0 0 16 8c0-4.42-3.58-8-8-8Z"/></svg>')
LINKEDIN_ICON = ('<svg class="brand-icon linkedin-icon" width="14" height="14" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
                 '<path fill="currentColor" d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.35V9h3.414v1.561h.049c.476-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286ZM5.337 7.433a2.062 2.062 0 1 1 0-4.124 2.062 2.062 0 0 1 0 4.124ZM3.56 9h3.554v11.452H3.56V9ZM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003Z"/></svg>')


def is_github_url(url):
    return (urlsplit(url).hostname or '').lower().removeprefix('www.') == 'github.com'


def profile_link(label, url):
    host = (urlsplit(url).hostname or '').lower().removeprefix('www.')
    if host == 'github.com':
        network, icon = 'github', GITHUB_ICON
    elif host.endswith('linkedin.com'):
        network, icon = 'linkedin', LINKEDIN_ICON
    else:
        network, icon = 'other', ''
    return '<a class="profile-link profile-link--{}" href="{}">{}<span>{}</span></a>'.format(
        network, esc(url), icon, esc(label))


def project_title_markup(title, url):
    colored_title = '<span class="project-title">{}</span>'.format(esc(title))
    if not url:
        return colored_title
    if is_github_url(url):
        label = esc('Open {} GitHub repository'.format(title))
        return '{} <a class="repo-button" href="{}" aria-label="{}">{}<span>GitHub</span></a>'.format(
            colored_title, esc(url), label, GITHUB_ICON)
    return '<a class="project-link" href="{}">{}</a>'.format(esc(url), esc(title))


def render_detail(text, detail_links):
    targets = {item['text']: item['url'] for item in detail_links}
    if not targets:
        return esc(text)
    pattern = re.compile('|'.join(re.escape(value) for value in sorted(targets, key=len, reverse=True)))
    output, offset = [], 0
    for match in pattern.finditer(text):
        output.append(esc(text[offset:match.start()]))
        output.append(link(match.group(0), targets[match.group(0)]))
        offset = match.end()
    output.append(esc(text[offset:]))
    return ''.join(output)


def render(data, template, style_version=''):
    labels = LABELS[data.get('language', 'en')]
    theme = data.get('theme', 'classic')
    background = data.get('background', THEMES[theme]['background'])
    profile = ''
    if data.get('avatar'):
        profile += '<span class="image avatar"><img src="{}" alt="{}"></span>'.format(esc(data['avatar']), esc(data['name']))
    profile += '<h1>{}</h1>'.format(esc(data['name']))
    position = ', '.join(filter(None, [data.get('position'), data.get('affiliation')]))
    if position:
        profile += '<p class="position">{}</p>'.format(esc(position))
    if data.get('degree'):
        profile += '<p class="degree">{}</p>'.format(esc(data['degree']))
    emails = list(dict.fromkeys(filter(None, [data.get('email', ''), *data.get('additional_emails', [])])))
    if emails:
        profile += '<p class="email">' + '<br>'.join(link(email, 'mailto:' + email) for email in emails) + '</p>'
    social = [profile_link(x['label'], x['url']) for x in data.get('links', [])]
    if data.get('cv'):
        social.append(link('CV', data['cv'], 'profile-link'))
    profile += '<div class="profile-links">' + ' '.join(social) + '</div>'
    sections, nav = [], []
    for key in data.get('section_order', ORDER):
        values = data.get(key, [])
        if not values:
            continue
        anchor = 'about-me' if key == 'about' else key
        nav.append(link(labels[key], '#' + anchor, 'normal'))
        content = ''
        if key == 'about':
            content = ''.join('<p>{}</p>'.format(esc(x)) for x in values)
        elif key in ('awards', 'skills'):
            content = '<ul>' + ''.join('<li>{}</li>'.format(esc(x)) for x in values) + '</ul>'
        elif key == 'publications':
            if data.get('publication_note'):
                content += '<p class="publication-note">{}</p>'.format(esc(data['publication_note']))
            content += '<div class="publications"><ol class="bibliography">'
            for pub in values:
                content += '<li><div class="pub-row">'
                if pub.get('image'):
                    content += '<div class="abbr"><img class="teaser" src="{}" alt="Figure for {}" loading="lazy">'.format(esc(pub['image']), esc(pub['title']))
                    if pub.get('badge'):
                        content += '<span class="badge">{}</span>'.format(esc(pub['badge']))
                    content += '</div>'
                content += '<div class="pub-body"><div class="title">{}</div>'.format(esc(pub['title']))
                content += '<div class="author">{}</div>'.format(esc(pub.get('authors', '')))
                venue = ' · '.join(filter(None, [pub.get('venue'), pub.get('year')]))
                content += '<div class="periodical"><em>{}</em></div>'.format(esc(venue))
                content += '<div class="links">' + ' '.join(link(x['label'], x['url'], 'btn') for x in pub.get('links', [])) + '</div>'
                if pub.get('notes'):
                    content += '<p class="pub-note">{}</p>'.format(esc(pub['notes']))
                content += '</div></div></li>'
            content += '</ol></div>'
        else:
            previous_group = None
            for item in values:
                group = item.get('group')
                if group and group != previous_group:
                    content += '<h3>{}</h3>'.format(esc(group))
                previous_group = group
                if key == 'projects':
                    title = project_title_markup(item['title'], item.get('url', ''))
                    if item.get('links'):
                        title += ' <span class="project-links">' + ' '.join(
                            link(x['label'], x['url'], 'btn')
                            for x in item['links']
                        ) + '</span>'
                else:
                    title = project_title_markup(item['title'], item['url']) if item.get('url') else esc(item['title'])
                content += '<div class="entry"><p><strong>{}</strong>'.format(title)
                if item.get('organization'):
                    content += '<br><em>{}</em>'.format(esc(item['organization']))
                if item.get('dates'):
                    content += ' <span class="dates">({})</span>'.format(esc(item['dates']))
                content += '</p>'
                if item.get('details'):
                    content += '<ul>' + ''.join('<li>{}</li>'.format(render_detail(x, item.get('detail_links', []))) for x in item['details']) + '</ul>'
                content += '</div>'
        sections.append('<article class="section-{3}" aria-labelledby="{0}"><h2 id="{0}">{1}</h2>{2}</article>'.format(anchor, labels[key], content, key))
    canonical = '<link rel="canonical" href="{}">'.format(esc(data['site_url'])) if data.get('site_url') else ''
    return Template(template).substitute(
        lang='zh-CN' if data.get('language') == 'zh' else 'en',
        title=esc(' | '.join(filter(None, [data['name'], data.get('affiliation')]))),
        description=esc(data.get('description') or ' '.join(data.get('about', []))[:180]),
        canonical=canonical, profile=profile, navigation=''.join(nav), sections='\n'.join(sections), menu=labels['menu'],
        theme=theme, background=background, style_version=style_version,
        particles_script='<script src="assets/js/particles.min.js" defer></script>' if background == 'particles' else '')


def build(root):
    root = Path(root).resolve()
    data = validate(json.loads((root / 'site.json').read_text(encoding='utf-8')), root)
    styles = [root / 'assets/css/site.css', root / 'assets/css/themes.css']
    style_version = hashlib.sha256(b''.join(path.read_bytes() for path in styles)).hexdigest()[:12]
    rendered = render(data, (root / 'template.html').read_text(encoding='utf-8'), style_version)
    docs = root / 'docs'
    marker = docs / '.cv-to-homepage'
    if docs.is_symlink() or (docs.exists() and not marker.is_file()):
        raise ValueError('Refusing to replace unmanaged docs directory.')
    if docs.exists():
        shutil.rmtree(docs)
    docs.mkdir()
    # Only referenced media plus shipped CSS/JS belong in the public artifact.
    for folder in ['css', 'js']:
        for source in (root / 'assets' / folder).glob('*'):
            if source.is_file() and not source.is_symlink() and source.suffix in ('.css', '.js'):
                dest = docs / 'assets' / folder / source.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, dest)
    media = [data.get('avatar'), data.get('cv')] + [p.get('image') for p in data.get('publications', [])]
    for relative in filter(None, media):
        relative = local_media(relative)
        dest = docs / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / relative, dest)
    (docs / 'index.html').write_text(rendered, encoding='utf-8')
    (docs / '.nojekyll').touch()
    marker.write_text('Generated public site. Rebuild with python3 build.py.\n')
    for name in ['LICENSE', 'ATTRIBUTION.md', 'THIRD_PARTY_LICENSES.txt']:
        if (root / name).is_file():
            shutil.copy2(root / name, docs / name)
    return docs


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    try:
        print(build(args.root))
    except (ValueError, OSError) as error:
        parser.exit(1, 'Build failed: ' + str(error) + '\n')
