// Builds the TipTap bundle the notes editor imports. The bundle is
// committed (static/js/vendor/tiptap.bundle.js), so deploys need no Node:
// run this by hand after upgrading TipTap, then commit the new bundle.
//
//   npm install && npm run build
//
// Lucide icons load from unpkg (see templates/base.html), not from here.

import * as esbuild from 'esbuild';

const isWatch = process.argv.includes('--watch');

const tiptapBuild = {
  entryPoints: ['src/tiptap.js'],
  bundle: true,
  format: 'esm',
  outfile: 'static/js/vendor/tiptap.bundle.js',
  minify: true,
  target: ['es2020'],
};

if (isWatch) {
  const context = await esbuild.context(tiptapBuild);
  await context.watch();
  console.log('Watching for changes...');
} else {
  await esbuild.build(tiptapBuild);
  console.log(`Build complete: ${tiptapBuild.outfile}`);
}
