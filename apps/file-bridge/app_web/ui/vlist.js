// Virtual list: fixed-height rows; only the visible rows (plus overscan) exist in the DOM, so 100,000 entries
// scroll as smoothly as 30. Rows are absolutely positioned inside a spacer of count * rowHeight. No layout reads
// during render except the container's height and scroll position, read once per frame.
(function () {
  "use strict";
  var NB = window.NB;

  function VList(viewport, opts) {
    this.vp = viewport;
    this.rowH = opts.rowHeight || 32;
    this.render = opts.render;           // function(index) -> HTML string for one row
    this.overscan = opts.overscan || 10;
    this.count = 0;
    this.spacer = document.createElement("div");
    this.spacer.className = "vl-spacer";
    this.layer = document.createElement("div");
    this.layer.className = "vl-layer";
    this.spacer.appendChild(this.layer);
    viewport.appendChild(this.spacer);
    var self = this, queued = false;
    this._schedule = function () {
      if (queued) { return; }
      queued = true;
      requestAnimationFrame(function () { queued = false; self.draw(); });
    };
    viewport.addEventListener("scroll", this._schedule, { passive: true });
    if (window.ResizeObserver) { new ResizeObserver(this._schedule).observe(viewport); }
  }
  VList.prototype.setCount = function (n) {
    this.count = n;
    this.spacer.style.height = (n * this.rowH) + "px";
    this.first = -1;
    this.draw();
  };
  VList.prototype.refresh = function () { this.first = -1; this.draw(); };
  VList.prototype.draw = function () {
    var h = this.vp.clientHeight || 400, top = this.vp.scrollTop;
    var first = Math.max(0, Math.floor(top / this.rowH) - this.overscan);
    var last = Math.min(this.count, Math.ceil((top + h) / this.rowH) + this.overscan);
    if (first === this.first && last === this.last) { return; }
    this.first = first;
    this.last = last;
    var html = [];
    for (var i = first; i < last; i++) { html.push(this.render(i)); }
    this.layer.style.transform = "translateY(" + (first * this.rowH) + "px)";
    this.layer.innerHTML = html.join("");
  };
  // Keep a row visible (keyboard navigation), accounting for a sticky header of `offset` px.
  VList.prototype.reveal = function (index) {
    var top = index * this.rowH, bottom = top + this.rowH, vp = this.vp;
    if (top < vp.scrollTop) { vp.scrollTop = top; }
    else if (bottom > vp.scrollTop + vp.clientHeight) { vp.scrollTop = bottom - vp.clientHeight; }
    this.first = -1;
    this.draw();
  };
  VList.prototype.pageSize = function () { return Math.max(1, Math.floor(this.vp.clientHeight / this.rowH) - 1); };

  NB.VList = VList;
})();
