from pydantic import BaseModel, Field, field_validator


class FormField(BaseModel):
    label: str
    placeholder: str


class FormFields(BaseModel):
    name: FormField
    phone: FormField
    subject: FormField
    message: FormField


class FormPublic(BaseModel):
    title: str
    subtitle: str
    cta: str
    hint: str
    fields: FormFields


class FormAdmin(FormPublic):
    is_active: bool


class FormFieldWrite(BaseModel):
    label: str = Field(default="", max_length=80)
    placeholder: str = Field(default="", max_length=160)

    @field_validator("label", "placeholder", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class FormFieldsWrite(BaseModel):
    name: FormFieldWrite = Field(default_factory=FormFieldWrite)
    phone: FormFieldWrite = Field(default_factory=FormFieldWrite)
    subject: FormFieldWrite = Field(default_factory=FormFieldWrite)
    message: FormFieldWrite = Field(default_factory=FormFieldWrite)


class FormWrite(BaseModel):
    is_active: bool = True
    title: str = Field(default="", max_length=200)
    subtitle: str = Field(default="", max_length=400)
    cta: str = Field(default="", max_length=80)
    hint: str = Field(default="", max_length=200)
    fields: FormFieldsWrite = Field(default_factory=FormFieldsWrite)

    @field_validator("title", "subtitle", "cta", "hint", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value
