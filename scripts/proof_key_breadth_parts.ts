// These source imports rely on Proof 0.34.1's package layout so incompatible upgrades fail at import time.
import { WorkingTree } from "../node_modules/@pi-innovations/proof/src/git";
import { keyParts } from "../node_modules/@pi-innovations/proof/src/key-parts";
import { currentTree } from "../node_modules/@pi-innovations/proof/src/plan";

const view = currentTree();
const rows = Bun.argv.slice(2).map((id) => {
  const task = view.tasks.get(id);
  if (!task) throw new Error(`Unknown Proof task: ${id}`);
  const { files, members, reasons } = keyParts(task, new WorkingTree(view.tree, view.dirty));
  return { task: id, files, members, reasons };
});
console.log(JSON.stringify(rows));
