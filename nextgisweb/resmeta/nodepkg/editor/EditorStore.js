import { toJS, makeAutoObservable } from "mobx";

function valueToType(v) {
    if (typeof v === "string") {
        return "string";
    } else if ((typeof v === "number") && (v === parseInt(v, 10))) {
        return "integer";
    } else if (typeof v === "number") {
        return "float";
    }
}

export class EditorStore {
    items = [];
    nextId = 0;

    constructor() {
        makeAutoObservable(this);
    }

    load(value) {
        this.items = Object.entries(value.items).map(([key, value], id) => ({
            id: id,
            placeholder: false,
            key: key,
            type: valueToType(value),
            value: value,
        }));
        this.nextId = this.items.length;
        this.addPlaceholder();
    }

    dump() {
        const items = {};
        this.items.forEach((itm) => {
            items[itm.key] = itm.value;
        });
        return { items: toJS(items) };
    }

    addPlaceholder() {
        if (
            this.items.length == 0 ||
            !this.items[this.items.length - 1].placeholder
        ) {
            this.items.push({ id: this.nextId, placeholder: true });
            this.nextId++;
        }
    }

    updateItem(id, data) {
        data.type = data.type || "string";
        const record = this.items.find((r) => r.id == id);
        record.key = data.key;
        record.value = data.value;
        if (record.type != data.type) {
            record.type = data.type;
            if (record.type == "string") {
                if (record.value == undefined || record.value == null) {
                    record.value = "";
                } else {
                    record.value = record.value.toString();
                }
            } else if (record.type == "integer") {
                record.value = parseInt(record.value);
                if (record.value == undefined || isNaN(record.value)) {
                    record.value = 0;
                }
            } else if (record.type == "float") {
                record.value = parseFloat(record.value);
                if (record.value == undefined || isNaN(record.value)) {
                    record.value = 0;
                }
            }
        }
        record.placeholder = false;
        this.addPlaceholder();
    }
}
