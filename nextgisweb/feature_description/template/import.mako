<%inherit file='nextgisweb:pyramid/template/base.mako' />

<%def name="head()">
    <script type="text/javascript">
        require([
            "ngw-feature-description/ImportForm",
            "dojo/domReady!",
        ], function (
            ImportForm,
        ) {
            (new ImportForm({resid: ${obj.id}})).placeAt('form').startup();
        });
    </script>
</%def>

<div id="form" style="width: 100%"></div>
