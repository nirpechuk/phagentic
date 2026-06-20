#!/usr/bin/env node
// PHAGENTIC build — assemble index.html from the source files.
//
//   src/shell.html          page shell (head, <helmet>, scripts, <!--@WIDGETS--> marker)
//   src/widgets/NN-*.html   one file per widget/section, concatenated in NN order
//   logic.js                the component class (loaded as a normal <script>)
//
// Run:  node build.js     (run.sh / `make ui` do this for you)
const fs = require("fs"), path = require("path");
const dir = __dirname;
const shell = fs.readFileSync(path.join(dir, "src/shell.html"), "utf8");
const wdir = path.join(dir, "src/widgets");
const files = fs.readdirSync(wdir).filter(f => f.endsWith(".html")).sort();
const widgets = files.map(f => fs.readFileSync(path.join(wdir, f), "utf8")).join("");
if (!shell.includes("<!--@WIDGETS-->")) { console.error("shell.html missing <!--@WIDGETS--> marker"); process.exit(1); }
fs.writeFileSync(path.join(dir, "index.html"), shell.replace("<!--@WIDGETS-->", widgets));
console.log("built index.html from " + files.length + " widgets:\n  " + files.join("\n  "));
