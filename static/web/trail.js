/**
 * Back, for a page that swaps views in place (a class's register, a fee account,
 * a marking sheet). A view that is "up" from the list carries `data-up="N"` on
 * its own way-back control (N is its depth). After each draw, `follow()` pushes
 * an entry per level gained, so Back pops one and presses that control; using
 * the control first drops the entries again.
 */
export function followBack(root) {
  if (typeof history === "undefined" || typeof addEventListener === "undefined") return () => {};
  let depth = 0;
  const up = () => root.querySelector("[data-up]");
  addEventListener("popstate", (event) => {
    const target = (event.state && event.state.depth) || 0;
    if (target < depth) {
      depth = target;
      if (up()) up().click();
    } else if (target > depth) history.back(); // forward into a view that is gone
  });
  return function follow() {
    const level = up() ? Number(up().dataset.up) : 0;
    const gone = depth - level;
    for (let d = depth + 1; d <= level; d++) history.pushState({ depth: d }, "");
    depth = level;
    if (gone > 0) history.go(-gone);
  };
}
