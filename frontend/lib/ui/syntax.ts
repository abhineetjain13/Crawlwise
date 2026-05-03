export function syntaxHighlightJson(json: string) {
  if (!json) return '';
  // Basic HTML escaping
  json = json.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  
  // Syntax highlighting regex
  return json.replace(
    /("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g,
    (match) => {
      let cls = 'syntax-number';
      if (/^"/.test(match)) {
        if (/:$/.test(match)) {
          cls = 'syntax-key';
        } else {
          cls = 'syntax-string';
        }
      } else if (/true|false/.test(match)) {
        cls = 'syntax-boolean';
      } else if (/null/.test(match)) {
        cls = 'syntax-null';
      }
      return `<span class="${cls}">${match}</span>`;
    },
  );
}
