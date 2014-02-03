//>>built
define("dojox/data/demos/widgets/FlickrViewList",["dijit","dojo","dojox","dojo/require!dojox/dtl/_Templated,dijit/_Widget"],function(_1,_2,_3){
_2.provide("dojox.data.demos.widgets.FlickrViewList");
_2.require("dojox.dtl._Templated");
_2.require("dijit._Widget");
_2.declare("dojox.data.demos.widgets.FlickrViewList",[_1._Widget,_3.dtl._Templated],{store:null,items:null,templateString:_2.cache("dojox","data/demos/widgets/templates/FlickrViewList.html","{% load dojox.dtl.contrib.data %}\n{% bind_data items to store as flickr %}\n<div dojoAttachPoint=\"list\">\n\t{% for item in flickr %}\n\t<div style=\"display: inline-block; align: top;\">\n\t\t<h5>{{ item.title }}</h5>\n\t\t<a href=\"{{ item.link }}\" style=\"border: none;\">\n\t\t\t<img src=\"{{ item.imageUrlMedium }}\">\n\t\t</a>\n\t\t<p>{{ item.author }}</p>\n\n\t\t<!--\n\t\t<img src=\"{{ item.imageUrl }}\">\n\t\t<p>{{ item.imageUrl }}</p>\n\t\t<img src=\"{{ item.imageUrlSmall }}\">\n\t\t-->\n\t</div>\n\t{% endfor %}\n</div>\n\n"),fetch:function(_4){
_4.onComplete=_2.hitch(this,"onComplete");
_4.onError=_2.hitch(this,"onError");
return this.store.fetch(_4);
},onError:function(){
this.items=[];
this.render();
},onComplete:function(_5,_6){
this.items=_5||[];
this.render();
}});
});
