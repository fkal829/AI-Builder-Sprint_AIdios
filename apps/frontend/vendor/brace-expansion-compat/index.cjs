"use strict";

/* eslint-disable @typescript-eslint/no-require-imports -- legacy minimatch loads this bridge through CommonJS */
const upstream = require("brace-expansion-upstream");
const expand = upstream.expand;

module.exports = expand;
module.exports.expand = expand;
module.exports.EXPANSION_MAX = upstream.EXPANSION_MAX;
module.exports.EXPANSION_MAX_LENGTH = upstream.EXPANSION_MAX_LENGTH;
