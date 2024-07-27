<%! from nextgisweb.resource.view import creatable_resources %>

<%page args="section" />
<% section.content_box = False %>

<%
    props = dict(resourceId=obj.id)

    summary = props["summary"] = []
    summary.append((tr(_("Type")), f"{tr(obj.cls_display_name)} ({obj.cls})"))
    if keyname := obj.keyname:
        summary.append((tr(_("Keyname")), keyname))

    if get_info := getattr(obj, 'get_info', None):
        for key, value in get_info():
            summary.append((tr(key), str(tr(value))))

    summary.append((tr(_("Owner")), tr(obj.owner_user.display_name_i18n)))

    if request.env.resource.options["experimental.actions"]:
        props["creatable"] = [c.identity for c in creatable_resources(obj, user=request.user)]
%>

<div id="resourceMainSection" class="ngw-resource-section"></div>

<script type="text/javascript">
    require([
        "@nextgisweb/resource/main-section",
        "@nextgisweb/gui/react-app",
    ], function (comp, reactApp) {
        reactApp.default(
            comp.default,
            ${json_js(props)},
            document.getElementById('resourceMainSection')
        );
    });
</script>
