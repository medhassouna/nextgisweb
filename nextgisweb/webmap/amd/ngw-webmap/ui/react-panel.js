define([
    "dojo/_base/declare",
    "dojo/dom-style",
    "dojo/promise/all",
    "dijit/_WidgetBase",
    "@nextgisweb/gui/react-app",
], function (declare, domStyle, all, _WidgetBase, reactApp) {
    return function (fcomp, { waitFor = [] } = {}) {
        return declare(fcomp.name, [_WidgetBase], {
            buildRendering: function () {
                this.inherited(arguments);
                domStyle.set(this.domNode, "height", "100%");
                const pm = this.display.panelsManager;

                all(waitFor).then(() => {
                    reactApp.default(
                        fcomp,
                        {
                            display: this.display,
                            title: this.title,
                            close: () => pm._closePanel(pm.getPanel("layers")),
                        },
                        this.domNode
                    );
                });
            },
        });
    };
});
