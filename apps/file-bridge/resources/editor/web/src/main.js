import * as monaco from 'monaco-editor';
import editorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker';
import jsonWorker from 'monaco-editor/esm/vs/language/json/json.worker?worker';
import cssWorker from 'monaco-editor/esm/vs/language/css/css.worker?worker';
import htmlWorker from 'monaco-editor/esm/vs/language/html/html.worker?worker';
import tsWorker from 'monaco-editor/esm/vs/language/typescript/ts.worker?worker';

self.MonacoEnvironment = {
  getWorker(_workerId, label) {
    if (label === 'json') return new jsonWorker();
    if (label === 'css' || label === 'scss' || label === 'less') return new cssWorker();
    if (label === 'html' || label === 'handlebars' || label === 'razor') return new htmlWorker();
    if (label === 'typescript' || label === 'javascript') return new tsWorker();
    return new editorWorker();
  }
};

let bridge;
let editor;
let diffEditor;
let model;
let currentSessionId = '';
let suppressChange = false;
let minimapEnabled = true;
let changeTimer;

monaco.editor.defineTheme('rfm-dark', {
  base: 'vs-dark', inherit: true, rules: [],
  colors: {
    'editor.background': '#080808', 'editor.foreground': '#CCCCCC',
    'editorLineNumber.foreground': '#6E7681', 'editorLineNumber.activeForeground': '#C6C6C6',
    'editorCursor.foreground': '#AEAFAD', 'editor.selectionBackground': '#264F78',
    'editor.inactiveSelectionBackground': '#3A3D41', 'editor.lineHighlightBackground': '#0F0F0F',
    'editorIndentGuide.background1': '#202020', 'editorIndentGuide.activeBackground1': '#3B3B3B',
    'editorWidget.background': '#202020', 'editorWidget.border': '#454545',
    'editorSuggestWidget.background': '#202020', 'editorSuggestWidget.border': '#454545',
    'editorSuggestWidget.selectedBackground': '#04395E', 'minimap.background': '#080808'
  }
});

function options(payload) {
  return {
    theme: 'rfm-dark', readOnly: !!payload.readonly, automaticLayout: true,
    fontFamily: "'Cascadia Code', 'JetBrains Mono', 'Fira Code', Consolas, monospace",
    fontSize: 13, lineHeight: 20, fontLigatures: true,
    minimap: { enabled: minimapEnabled, maxColumn: 100, renderCharacters: false },
    smoothScrolling: true, cursorSmoothCaretAnimation: 'on', bracketPairColorization: { enabled: true },
    guides: { bracketPairs: true, indentation: true, highlightActiveIndentation: true },
    folding: true, glyphMargin: true, stickyScroll: { enabled: true }, inlineSuggest: { enabled: true },
    quickSuggestions: { other: true, comments: false, strings: true }, parameterHints: { enabled: true },
    mouseWheelZoom: true, padding: { top: 6, bottom: 8 }, scrollBeyondLastLine: false, overviewRulerBorder: false
  };
}

function dispose() {
  if (editor) editor.dispose();
  if (diffEditor) diffEditor.dispose();
  if (model) model.dispose();
  editor = diffEditor = model = null;
  document.getElementById('editor').innerHTML = '';
}

function installEvents(instance) {
  instance.onDidChangeModelContent(() => {
    if (suppressChange || !model) return;
    clearTimeout(changeTimer);
    changeTimer = setTimeout(() => bridge?.contentChangedFromWeb(currentSessionId, model.getValue()), 120);
  });
  instance.onDidChangeCursorPosition(e => bridge?.cursorChangedFromWeb(currentSessionId, e.position.lineNumber, e.position.column));
  instance.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => bridge?.saveFromWeb(currentSessionId, model.getValue()));
}

function loadDocument(payload) {
  if (!payload || payload.empty || !payload.sessionId) { currentSessionId = ''; dispose(); return; }
  const same = currentSessionId === payload.sessionId && model && editor;
  currentSessionId = payload.sessionId;
  if (!same) {
    dispose();
    const uri = monaco.Uri.parse((payload.remote ? 'rfm-remote:///' : 'file:///') + encodeURIComponent(payload.path || payload.title));
    model = monaco.editor.createModel(payload.text || '', payload.language || 'plaintext', uri);
    editor = monaco.editor.create(document.getElementById('editor'), options(payload));
    editor.setModel(model);
    installEvents(editor);
  } else {
    monaco.editor.setModelLanguage(model, payload.language || 'plaintext');
    editor.updateOptions({ readOnly: !!payload.readonly });
    if (model.getValue() !== (payload.text || '')) { suppressChange = true; model.setValue(payload.text || ''); suppressChange = false; }
  }
  editor.focus();
}

function showDiff(payload) {
  dispose();
  currentSessionId = payload.sessionId;
  diffEditor = monaco.editor.createDiffEditor(document.getElementById('editor'), {
    theme: 'rfm-dark', automaticLayout: true, readOnly: true, originalEditable: false,
    renderSideBySide: innerWidth > 1000, fontFamily: "'Cascadia Code', Consolas, monospace", fontSize: 13,
    lineHeight: 20, minimap: { enabled: false }, scrollBeyondLastLine: false
  });
  diffEditor.setModel({
    original: monaco.editor.createModel(payload.original || '', payload.language || 'plaintext'),
    modified: monaco.editor.createModel(payload.modified || '', payload.language || 'plaintext')
  });
}

function command(name) {
  if (name === 'save') return bridge?.saveFromWeb(currentSessionId, model?.getValue() || '');
  if (name === 'focus') return editor?.focus();
  if (name === 'find') return editor?.getAction('actions.find')?.run();
  if (name === 'replace') return editor?.getAction('editor.action.startFindReplaceAction')?.run();
  if (name === 'gotoLine') return editor?.getAction('editor.action.gotoLine')?.run();
  if (name === 'format') return editor?.getAction('editor.action.formatDocument')?.run();
  if (name === 'toggleMinimap') { minimapEnabled = !minimapEnabled; editor?.updateOptions({ minimap: { enabled: minimapEnabled } }); }
}

new QWebChannel(qt.webChannelTransport, channel => {
  bridge = channel.objects.editorController;
  bridge.documentChanged.connect(loadDocument);
  bridge.commandRequested.connect(command);
  bridge.diffRequested.connect(showDiff);
  bridge.webReady();
});
