import { useRef, useEffect, createContext, useContext } from "react";
import { toJS } from "mobx";
import { observer } from "mobx-react-lite";
import { Table, Input, InputNumber, Form, Select } from "@nextgisweb/gui/antd";

const { Column } = Table;
const { Option } = Select;

const EditableContext = createContext(null);

const ValueWidget = ({ type, ...props }) => {
    if (type == "string") {
        return <Input {...props} />;
    } else if (type == "integer") {
        return <InputNumber precision={0} {...props} />;
    } else if (type == "float") {
        return <InputNumber {...props} />;
    } else {
        return <span>###</span>;
    }
};

const EditableRow = ({ index, record, store, ...props }) => {
    const [form] = Form.useForm();

    if (record === undefined) {
        return <tr {...props} />;
    }

    return (
        <Form
            form={form}
            component={false}
            initialValues={{
                key: toJS(record.key),
                type: toJS(record.type),
                value: toJS(record.value),
            }}
            validateTrigger="onBlur"
            onValuesChange={(_, data) => {
                store.updateItem(record.id, data);
                console.log(toJS(record));
                form.setFieldsValue(toJS(record));
            }}
        >
            <EditableContext.Provider value={form}>
                <tr {...props} />
            </EditableContext.Provider>
        </Form>
    );
};

const EditableCell = ({
    title,
    editable,
    children,
    dataIndex,
    record,
    store,
    handleSave,
    ...restProps
}) => {
    let childNode = children;
    if (record == undefined) {
        return <td {...restProps}>{childNode}</td>;
    }

    const form = useContext(EditableContext);

    let cellWidget;
    if (dataIndex == "key") {
        cellWidget = (
            <Input
                bordered={false}
                placeholder={
                    (record.placeholder && "Type here to add an item...") || ""
                }
            />
        );
    } else if (dataIndex == "type") {
        cellWidget = (
            <Select bordered={false}>
                <Option value="string">String</Option>
                <Option value="integer">Integer</Option>
                <Option value="float">Float</Option>
            </Select>
        );
    } else if (dataIndex == "value") {
        cellWidget = <ValueWidget type={record.type} />;
    }

    return (
        <td>
            <Form.Item name={dataIndex} noStyle={true}>
                {cellWidget}
            </Form.Item>
        </td>
    );
};

export const EditorWidget = observer(({ store }) => {
    return (
        <Table
            rowKey="id"
            dataSource={store.items.slice()}
            pagination={false}
            size="small"
            components={{ body: { row: EditableRow, cell: EditableCell } }}
            onRow={(record, index) => ({ record, index, store })}
        >
            <Column
                title="Key"
                dataIndex="key"
                onCell={(record) => ({ record, store, dataIndex: "key" })}
            />
            <Column
                title="Type"
                dataIndex="type"
                onCell={(record) => ({ record, store, dataIndex: "type" })}
            />
            <Column
                title="Value"
                dataIndex="value"
                onCell={(record) => ({ record, store, dataIndex: "value" })}
            />
        </Table>
    );
    // return <div>{JSON.stringify(store.items)}</div>;
});
