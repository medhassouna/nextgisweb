define([
    "dojo/_base/declare",
    "dijit/_WidgetBase",
    "dijit/_TemplatedMixin",
    "dijit/_WidgetsInTemplateMixin",
    "@nextgisweb/pyramid/api",
    "ngw-pyramid/ErrorDialog/ErrorDialog",
    "@nextgisweb/pyramid/i18n!",
    "dojo/text!./template/ImportDialog.hbs",
    // template
    "dijit/form/Button",
    "ngw-file-upload/Uploader",
], function (
    declare,
    _WidgetBase,
    _TemplatedMixin,
    _WidgetsInTemplateMixin,
    api,
    ErrorDialog,
    i18n,
    template
) {
    return declare([_WidgetBase, _TemplatedMixin, _WidgetsInTemplateMixin], {
        templateString: i18n.renderTemplate(template),

        startup: function () {
            this.inherited(arguments);
            this.wFile.setAccept('application/zip');
            this.buttonImport.on("click", this.import_attachments.bind(this));
        },

        import_attachments: function () {
            var upload_meta = this.wFile.get("value");
            if (!upload_meta) {
                new ErrorDialog({
                    title: i18n.gettext("Validation error"),
                    message: i18n.gettext("File not uploaded.")
                }).show();
                return
            }
            var data = { source: upload_meta };
            api.route('feature_attachment.import', {id: this.resid}).put({
                json: data,
            }).then(
                function () {
                    window.location = api.routeURL('feature_layer.feature.browse', {id: this.resid});
                }.bind(this),
                function (err) { new ErrorDialog(err).show() }
            );
        }
    });
});
