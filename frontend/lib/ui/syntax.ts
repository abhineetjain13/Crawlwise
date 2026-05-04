export function syntaxHighlightJson(json: string) {
  if (!json) return '';

  const highlighted = json.replace(
    /("(\\u[a-fA-F0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d+)?(?:[eE][+\-]?\d+)?|[\{\}\[\],])/g,
    (match) => {
      // Escape before wrapping
      const escaped = match
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');

      if (/^[\{\}\[\],]$/.test(match)) {
        return `<span class="syntax-punct">${escaped}</span>`;
      }
      let cls = 'syntax-number';
      if (/^"/.test(match)) {
        if (/:$/.test(match)) {
          cls = 'syntax-key';
        } else {
          cls = 'syntax-string';
        }
      } else if (match === 'true' || match === 'false') {
        cls = 'syntax-boolean';
      } else if (match === 'null') {
        cls = 'syntax-null';
      }
      return `<span class="${cls}">${escaped}</span>`;
    },
  );

  return highlighted
    .split('\n')
    .map((line) => {
      const match = line.match(/^(\s*)/);
      const spaces = match ? match[1].length : 0;
      // Add 4ch so that wrapped text aligns cleanly past the key
      const indent = spaces + 4;
      return `<span style="display: block; padding-left: ${indent}ch; text-indent: -${indent}ch;">${line}</span>`;
    })
    .join('');
}
