define([
    "dojo/_base/declare",
    "dojo/dom-construct",
    "openlayers/ol",
    "@nextgisweb/pyramid/icon",
], function (declare, domConstruct, ol, icon) {
    return declare(ol.control.Control, {
        element: undefined,
        target: undefined,
        tipLabel: undefined,

        constructor: function (options) {
            this.inherited(arguments);
            declare.safeMixin(this, options);

            this.element = domConstruct.create("div", {
                class: "ol-control ol-unselectable",
                title: this.tipLabel,
            });

            domConstruct.create(
                "a",
                {
                    href: this.url,
                    target: "_blank",
                    class: "ol-control__btn",
                    innerHTML: icon.html({ glyph: "open_in_new" }),
                },
                this.element
            );

            ol.control.Control.call(this, {
                element: this.element,
                target: this.target,
            });
        },
    });
});
