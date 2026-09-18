document.querySelectorAll('[data-faculty-tree]').forEach((tree) => {
  const search = tree.querySelector('[data-tree-search]');
  const root = tree.querySelector('[data-tree-root]');
  const nodes = [...tree.querySelectorAll('[data-tree-node]')];
  const empty = tree.querySelector('[data-tree-empty]');

  search.addEventListener('input', () => {
    const query = search.value.trim().toLocaleLowerCase('ru-RU');
    let matches = 0;

    nodes.forEach((node) => {
      const words = node.dataset.searchText.split(/[\s,.-]+/u);
      const visible = !query || words.some((word) => word.startsWith(query));
      node.hidden = !visible;
      if (visible) matches += 1;
    });

    root.setAttribute('aria-expanded', 'true');
    empty.hidden = matches !== 0;
  });
});
