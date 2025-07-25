from flask import Flask, render_template, request, abort, session, redirect
import os
import git
import markdown
from pygments import highlight
from pygments.lexers import get_lexer_by_name, TextLexer
from pygments.formatters import HtmlFormatter
import re

app = Flask(__name__)
app.secret_key = 'your_secret_key_here_12345'
REPOS_DIR = os.path.join(os.getcwd(), 'repos')

os.makedirs(REPOS_DIR, exist_ok=True)


def get_file_content(repo_path, file_path):
    """Получить содержимое файла с подсветкой синтаксиса"""
    full_path = os.path.join(repo_path, file_path)
    if not os.path.exists(full_path):
        return None

    try:
        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Определяем язык по расширению файла
        lexer = TextLexer()
        if '.' in file_path:
            ext = file_path.split('.')[-1].lower()
            lang_map = {
                'py': 'python',
                'js': 'javascript',
                'html': 'html',
                'htm': 'html',
                'css': 'css',
                'json': 'json',
                'xml': 'xml',
                'sql': 'sql',
                'sh': 'bash',
                'md': 'markdown',
                'yaml': 'yaml',
                'yml': 'yaml',
                'java': 'java',
                'cpp': 'cpp',
                'c': 'c',
                'php': 'php',
                'rb': 'ruby',
                'go': 'go',
                'rs': 'rust'
            }
            if ext in lang_map:
                try:
                    lexer = get_lexer_by_name(lang_map[ext])
                except:
                    lexer = TextLexer()

        # Выбираем стиль в зависимости от темы
        theme = session.get('theme', 'light')
        style = 'monokai' if theme == 'dark' else 'default'

        formatter = HtmlFormatter(style=style, cssclass="highlight")
        highlighted = highlight(content, lexer, formatter)

        # Добавляем кнопку копирования для файлов кода (с текстом)
        if ext in ['py', 'js', 'html', 'css', 'json', 'xml', 'sql', 'sh', 'md', 'yaml', 'yml', 'java', 'cpp', 'c',
                   'php', 'rb', 'go', 'rs']:
            # Экранируем кавычки для JavaScript
            escaped_content = content.replace('\\', '\\\\').replace('"', '&quot;').replace('\n', '\\n').replace('\r',
                                                                                                                '')
            copy_button = f'''
            <div class="code-header">
                <span class="language-badge badge bg-secondary">{lang_map.get(ext, ext)}</span>
                <button class="btn btn-sm btn-outline-secondary copy-btn" 
                        onclick="copyCode(this)" 
                        data-code="{escaped_content}">
                    <i class="fas fa-copy"></i> Копировать
                </button>
            </div>
            '''
            return f'<div class="code-block-wrapper">{copy_button}<div class="file-content">{highlighted}</div></div>'
        else:
            return highlighted

    except UnicodeDecodeError:
        # Бинарный файл
        return "<pre>Бинарный файл - просмотр недоступен</pre>"
    except Exception as e:
        return f"<pre>Ошибка: {str(e)}</pre>"


def get_readme_content(repo_path):
    """Получить содержимое README.md с форматированием и подсветкой кода"""
    readme_files = ['README.md', 'readme.md', 'Readme.md']

    for readme_file in readme_files:
        readme_path = os.path.join(repo_path, readme_file)
        if os.path.exists(readme_path):
            try:
                with open(readme_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                # Определяем тему для подсветки
                theme = session.get('theme', 'light')

                # Обрабатываем блоки кода в README.md
                def code_block_replacer(match):
                    language = match.group(1) if match.group(1) else 'text'
                    code = match.group(2)

                    try:
                        lexer = get_lexer_by_name(language)
                    except:
                        lexer = TextLexer()

                    style = 'monokai' if theme == 'dark' else 'default'
                    formatter = HtmlFormatter(style=style, cssclass="highlight")
                    highlighted = highlight(code, lexer, formatter)

                    # Экранируем код для data-атрибута
                    escaped_code = code.replace('\\', '\\\\').replace('"', '&quot;').replace('\n', '\\n').replace('\r',
                                                                                                                  '')

                    # Кнопка копирования только с иконкой для README.md
                    copy_button = f'''
                    <button class="readme-copy-btn" 
                            onclick="copyCode(this)" 
                            data-code="{escaped_code}">
                        <i class="fas fa-copy"></i>
                    </button>
                    '''

                    return f'<div class="readme-code-header">{copy_button}{highlighted}</div>'

                # Обрабатываем блоки кода ```language
                content = re.sub(r'```(\w+)?\n(.*?)\n```', code_block_replacer, content, flags=re.DOTALL)

                # Конвертируем остальной Markdown
                html_content = markdown.markdown(content, extensions=[
                    'tables',
                    'nl2br'
                ])

                return html_content

            except Exception as e:
                return f"<p>Ошибка при чтении README.md: {str(e)}</p>"

    return None


@app.route('/toggle-theme')
def toggle_theme():
    """Переключение темы"""
    current_theme = session.get('theme', 'light')
    session['theme'] = 'dark' if current_theme == 'light' else 'light'
    return_to = request.args.get('return_to', '/')
    return redirect(return_to)


@app.route('/')
def index():
    repos = []
    for name in os.listdir(REPOS_DIR):
        repo_path = os.path.join(REPOS_DIR, name)
        if os.path.isdir(repo_path):
            try:
                repo = git.Repo(repo_path)
                last_commit = next(repo.iter_commits(max_count=1))
                repos.append({
                    'name': name,
                    'last_commit': last_commit.summary,
                    'last_commit_date': last_commit.committed_datetime.strftime('%Y-%m-%d'),
                    'branch': repo.active_branch.name if not repo.head.is_detached else 'detached'
                })
            except:
                repos.append({
                    'name': name,
                    'last_commit': 'Ошибка загрузки',
                    'last_commit_date': '',
                    'branch': 'unknown'
                })

    theme = session.get('theme', 'light')
    return render_template('index.html', repos=repos, theme=theme)


@app.route('/repo/<repo_name>')
@app.route('/repo/<repo_name>/<path:subpath>')
def view_repo(repo_name, subpath=''):
    repo_path = os.path.join(REPOS_DIR, repo_name)
    if not os.path.exists(repo_path):
        abort(404)

    try:
        repo = git.Repo(repo_path)

        # Если указан конкретный файл - показываем его содержимое
        full_subpath = os.path.join(repo_path, subpath) if subpath else repo_path

        if os.path.isfile(full_subpath):
            # Это файл - показываем его содержимое
            content = get_file_content(repo_path, subpath)
            if content is None:
                abort(404)
            theme = session.get('theme', 'light')
            return render_template('file_content.html',
                                   repo_name=repo_name,
                                   file_path=subpath,
                                   content=content,
                                   theme=theme)

        # Это папка - показываем содержимое
        tree_items = []
        commits = list(repo.iter_commits(max_count=10))

        # Получаем содержимое текущей директории
        if subpath:
            # Для поддиректорий нужно найти соответствующий tree
            try:
                tree = repo.tree()
                for part in subpath.split('/'):
                    tree = tree[part]
                if tree.type == 'tree':
                    items = tree
                else:
                    # Это файл
                    content = get_file_content(repo_path, subpath)
                    theme = session.get('theme', 'light')
                    return render_template('file_content.html',
                                           repo_name=repo_name,
                                           file_path=subpath,
                                           content=content,
                                           theme=theme)
            except:
                abort(404)
        else:
            # Корневая директория
            items = repo.tree()

        # Преобразуем элементы в список для отображения
        if hasattr(items, 'trees'):
            # Это корневой tree
            for item in items.trees:
                tree_items.append({
                    'name': item.name,
                    'type': 'dir',
                    'path': item.path
                })
            for item in items.blobs:
                tree_items.append({
                    'name': item.name,
                    'type': 'file',
                    'path': item.path
                })
        else:
            # Это поддиректория
            for item in items:
                tree_items.append({
                    'name': item.name,
                    'type': 'dir' if item.type == 'tree' else 'file',
                    'path': item.path
                })

        # Получаем README.md для корневой директории
        readme_content = None
        if not subpath:  # Только для корня репозитория
            readme_content = get_readme_content(repo_path)

        # Путь для хлебных крошек
        path_parts = []
        if subpath:
            parts = subpath.split('/')
            for i in range(len(parts)):
                path_parts.append({
                    'name': parts[i],
                    'path': '/'.join(parts[:i + 1])
                })

        theme = session.get('theme', 'light')
        return render_template('repo.html',
                               repo_name=repo_name,
                               repo=repo,
                               tree_items=tree_items,
                               commits=commits,
                               current_path=subpath,
                               path_parts=path_parts,
                               readme_content=readme_content,
                               theme=theme)

    except Exception as e:
        return f"Ошибка при открытии репозитория: {e}", 500


if __name__ == '__main__':
    app.run(debug=True)